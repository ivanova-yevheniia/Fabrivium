import { useCallback, useEffect, useRef, useState } from "react";

/** Phase 14 §2/§3 — browser-native dictation for the customer brief. */

// Minimal structural types — the DOM lib does not ship SpeechRecognition.
interface SpeechRecognitionAlternativeLike {
  transcript: string;
}
interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: SpeechRecognitionAlternativeLike;
  length: number;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}
interface SpeechRecognitionErrorEventLike {
  error: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export type SpeechStatus = "idle" | "listening" | "denied" | "error";

export interface SpeechInput {
  /** False in a browser without the Web Speech API. */
  supported: boolean;
  status: SpeechStatus;
  /** Text recognised but not yet final — shown as a hint, never committed. */
  interim: string;
  /** Human-readable reason when status is "denied" or "error". */
  message: string | null;
  start: () => void;
  stop: () => void;
}

/** @param onFinalText called with each finalised phrase. */
export function useSpeechInput(onFinalText: (text: string) => void): SpeechInput {
  const [supported] = useState(() => recognitionConstructor() !== null);
  const [status, setStatus] = useState<SpeechStatus>("idle");
  const [interim, setInterim] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // Held in a ref so restarting recognition never captures a stale callback.
  const onFinalRef = useRef(onFinalText);
  onFinalRef.current = onFinalText;

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setInterim("");
    setStatus("idle");
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionConstructor();
    if (!Ctor) return;

    // Requested here, and only here: pressing the button is the consent.
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) finalText += text;
        else interimText += text;
      }
      setInterim(interimText);
      if (finalText.trim()) onFinalRef.current(finalText.trim());
    };

    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setStatus("denied");
        setMessage("Microphone access was declined. You can type or paste the brief instead.");
      } else if (event.error === "no-speech") {
        // Not a failure worth interrupting a presentation over.
        setStatus("idle");
      } else {
        setStatus("error");
        setMessage("Dictation stopped unexpectedly. You can type or paste the brief instead.");
      }
      setInterim("");
      recognitionRef.current = null;
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      setInterim("");
      setStatus((current) => (current === "listening" ? "idle" : current));
    };

    recognitionRef.current = recognition;
    setMessage(null);
    setStatus("listening");
    try {
      recognition.start();
    } catch {
      setStatus("listening");
    }
  }, []);

  // Never leave the microphone open when the screen goes away.
  useEffect(() => () => recognitionRef.current?.abort(), []);

  return { supported, status, interim, message, start, stop };
}
