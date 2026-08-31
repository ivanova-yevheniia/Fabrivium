import { useCallback } from "react";
import { useAppContext } from "../state/AppContext";
import { stationName } from "./formatting";

/** Audit §2 — resolve a machine id to the name the engineer gave the station. */
export function useStationName(): (machineId: string | null | undefined) => string {
  const { state } = useAppContext();
  const machines = state.factory?.machines ?? null;
  return useCallback((machineId: string | null | undefined) => stationName(machineId, machines), [machines]);
}
