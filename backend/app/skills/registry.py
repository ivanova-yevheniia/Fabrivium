"""The skill registry."""

from __future__ import annotations

from dataclasses import dataclass

from app.skills.contract import Skill, SkillCategory, SkillDefinition


class SkillRegistrationError(ValueError):
    """A skill could not be registered."""


class SkillNotFound(KeyError):
    """No enabled skill matches the request."""


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a dotted version."""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@dataclass(frozen=True)
class RegisteredSkill:
    skill: Skill
    definition: SkillDefinition
    #: Runtime override of the definition's own `enabled`, so a skill can be
    #: switched off without editing its declaration.
    enabled: bool = True

    @property
    def active(self) -> bool:
        return self.enabled and self.definition.enabled


class SkillRegistry:
    """Everything Fabrivium can do, and what each thing needs."""

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, RegisteredSkill]] = {}

    # Registration

    def register(self, skill: Skill, *, enabled: bool = True) -> SkillDefinition:
        definition = skill.definition
        by_version = self._skills.setdefault(definition.id, {})

        if definition.version in by_version:
            existing = by_version[definition.version].definition
            raise SkillRegistrationError(
                f"'{definition.id}' version {definition.version} is already registered "
                f"(as '{existing.name}'). Two skills sharing an id and a version makes "
                f"behaviour depend on registration order."
            )

        by_version[definition.version] = RegisteredSkill(
            skill=skill, definition=definition, enabled=enabled
        )
        return definition

    def unregister(self, skill_id: str, version: str | None = None) -> None:
        if skill_id not in self._skills:
            raise SkillNotFound(f"No skill '{skill_id}' is registered.")
        if version is None:
            del self._skills[skill_id]
            return
        if version not in self._skills[skill_id]:
            raise SkillNotFound(f"Skill '{skill_id}' has no version {version}.")
        del self._skills[skill_id][version]
        if not self._skills[skill_id]:
            del self._skills[skill_id]

    # Lookup

    def get(self, skill_id: str, version: str | None = None) -> Skill:
        """The skill for this id — newest enabled version unless asked otherwise."""
        entry = self._entry(skill_id, version)
        return entry.skill

    def definition(self, skill_id: str, version: str | None = None) -> SkillDefinition:
        return self._entry(skill_id, version).definition

    def _entry(self, skill_id: str, version: str | None) -> RegisteredSkill:
        versions = self._skills.get(skill_id)
        if not versions:
            raise SkillNotFound(f"No skill '{skill_id}' is registered.")

        if version is not None:
            entry = versions.get(version)
            if entry is None:
                available = ", ".join(sorted(versions))
                raise SkillNotFound(
                    f"Skill '{skill_id}' has no version {version}. Registered: {available}."
                )
            if not entry.active:
                raise SkillNotFound(f"Skill '{skill_id}@{version}' is disabled.")
            return entry

        active = [e for e in versions.values() if e.active]
        if not active:
            raise SkillNotFound(f"Every version of skill '{skill_id}' is disabled.")
        return max(active, key=lambda e: _version_key(e.definition.version))

    def has(self, skill_id: str) -> bool:
        versions = self._skills.get(skill_id)
        return bool(versions) and any(e.active for e in versions.values())

    # Discovery

    def list_enabled(self) -> list[SkillDefinition]:
        """Every active skill, newest version of each, in a stable order."""
        out: list[SkillDefinition] = []
        for skill_id in sorted(self._skills):
            try:
                out.append(self.definition(skill_id))
            except SkillNotFound:
                continue  # every version disabled
        return out

    def list_all(self) -> list[SkillDefinition]:
        """Every registered version, including disabled ones."""
        return [
            entry.definition
            for skill_id in sorted(self._skills)
            for _, entry in sorted(self._skills[skill_id].items())
        ]

    def find_by_capability(self, capability: str) -> list[SkillDefinition]:
        """Active skills offering a capability, best first."""
        matches = [d for d in self.list_enabled() if capability in d.capabilities]
        return sorted(matches, key=lambda d: (-d.priority, _version_key(d.version)), reverse=False)

    def find_by_category(self, category: SkillCategory) -> list[SkillDefinition]:
        return [d for d in self.list_enabled() if d.category is category]

    # Enable / disable

    def set_enabled(self, skill_id: str, enabled: bool, version: str | None = None) -> None:
        versions = self._skills.get(skill_id)
        if not versions:
            raise SkillNotFound(f"No skill '{skill_id}' is registered.")
        targets = [version] if version is not None else list(versions)
        for target in targets:
            entry = versions.get(target)
            if entry is None:
                raise SkillNotFound(f"Skill '{skill_id}' has no version {target}.")
            versions[target] = RegisteredSkill(
                skill=entry.skill, definition=entry.definition, enabled=enabled
            )

    # Prerequisites

    def missing_prerequisites(self, skill_id: str, version: str | None = None) -> list[str]:
        """Prerequisite skills that are absent or disabled."""
        definition = self.definition(skill_id, version)
        return [p for p in definition.prerequisites if not self.has(p)]

    def resolve_order(self, skill_ids: list[str]) -> list[str]:
        """Order these skills so prerequisites come first."""
        wanted = list(dict.fromkeys(skill_ids))
        within = set(wanted)
        ordered: list[str] = []
        placed: set[str] = set()

        def place(skill_id: str, seen: frozenset[str]) -> None:
            if skill_id in placed:
                return
            if skill_id in seen:
                cycle = " -> ".join([*seen, skill_id])
                raise SkillRegistrationError(f"Skills depend on each other in a cycle: {cycle}")
            for prerequisite in self.definition(skill_id).prerequisites:
                if prerequisite in within:
                    place(prerequisite, seen | {skill_id})
            placed.add(skill_id)
            ordered.append(skill_id)

        for skill_id in wanted:
            place(skill_id, frozenset())
        return ordered


# The process-wide registry.
default_registry = SkillRegistry()
