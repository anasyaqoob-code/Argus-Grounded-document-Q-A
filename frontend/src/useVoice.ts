/** Voice input + output hooks for Argus.
 *
 * Primary STT: browser Web Speech API — streams interim results live.
 * Fallback STT: Groq Whisper — used when Web Speech API is unavailable.
 *
 * useSpeech — Text-to-speech via browser SpeechSynthesis with a
 * user-selectable voice persisted in localStorage.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API } from "./api";

// ---------------------------------------------------------------------------
// Browser capability detection — SpeechRecognition
// ---------------------------------------------------------------------------
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message?: string;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  onerror: ((e: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

type SpeechRecognitionCtor = new () => SpeechRecognition;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

// ---------------------------------------------------------------------------
// useVoiceRecorder — mic capture → live transcript or Whisper fallback
// ---------------------------------------------------------------------------
export type VoiceRecorderState =
  | "idle"
  | "requesting"
  | "recording"
  | "transcribing"
  | "error";

export interface VoiceRecorderApi {
  state: VoiceRecorderState;
  error: string | null;
  supported: boolean;
  liveCapable: boolean;
  start: () => Promise<void>;
  stop: () => void;
  cancel: () => void;
}

export function useVoiceRecorder(
  onTranscript: (text: string) => void,
  onPartial?: (text: string) => void,
): VoiceRecorderApi {
  const [state, setState] = useState<VoiceRecorderState>("idle");
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const finalTextRef = useRef<string>("");

  const ctor = getSpeechRecognitionCtor();
  const supported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia;
  const liveCapable = ctor !== null;

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.abort();
      } catch {
        /* ignore */
      }
      try {
        mediaRecorderRef.current?.stop();
      } catch {
        /* ignore */
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const _cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const cancel = useCallback(() => {
    try {
      recognitionRef.current?.abort();
    } catch {
      /* ignore */
    }
    try {
      mediaRecorderRef.current?.stop();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    finalTextRef.current = "";
    _cleanupStream();
    setState("idle");
    setError(null);
  }, [_cleanupStream]);

  // ---- Live path: browser Web Speech API -----------------------------
  const _startLive = useCallback(async () => {
    if (!ctor) return;

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("error");
      setError(
        "Microphone access denied. Check your browser permissions and try again.",
      );
      return;
    }
    streamRef.current = stream;

    const recognition = new ctor();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    finalTextRef.current = "";

    recognition.onstart = () => setState("recording");

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      // Rebuild the entire transcript on every event — never append.
      // The browser re-fires the same phrase (interim then final), so
      // appending duplicates it. Rebuilding is idempotent.
      let finalText = "";
      let interimText = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0].transcript;
        if (result.isFinal) {
          finalText += transcript + " ";
        } else {
          interimText += transcript;
        }
      }
      finalTextRef.current = finalText;
      const composed = (finalText + interimText).trim();
      if (onPartial) onPartial(composed);
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        setError("Microphone permission denied.");
        setState("error");
        return;
      }
      if (event.error === "no-speech") {
        setError("No speech detected. Try again.");
        setState("error");
        return;
      }
      if (event.error === "aborted") return;
      setError(`Speech error: ${event.error}`);
      setState("error");
    };

    recognition.onend = () => {
      _cleanupStream();
      recognitionRef.current = null;

      const finalText = finalTextRef.current.trim();
      if (finalText) {
        onTranscript(finalText);
      }
      setState("idle");
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
    } catch (e) {
      _cleanupStream();
      setState("error");
      setError(`Could not start speech recognition: ${e}`);
    }
  }, [ctor, onTranscript, onPartial, _cleanupStream]);

  // ---- Fallback path: MediaRecorder → Groq Whisper -------------------
  const _startWhisper = useCallback(async () => {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("error");
      setError(
        "Microphone access denied. Check your browser permissions and try again.",
      );
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];

    const mimeCandidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    const mimeType = mimeCandidates.find(
      (m) =>
        typeof MediaRecorder !== "undefined" &&
        MediaRecorder.isTypeSupported?.(m),
    );

    let recorder: MediaRecorder;
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
    } catch {
      _cleanupStream();
      setState("error");
      setError("MediaRecorder is not supported in this browser.");
      return;
    }

    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data);
    };

    recorder.onerror = () => {
      _cleanupStream();
      setState("error");
      setError("Recording failed. Try again.");
    };

    recorder.onstop = async () => {
      _cleanupStream();

      const chunks = chunksRef.current;
      chunksRef.current = [];
      mediaRecorderRef.current = null;

      if (!chunks.length) {
        setState("idle");
        return;
      }

      const blob = new Blob(chunks, {
        type: recorder.mimeType || "audio/webm",
      });

      setState("transcribing");

      try {
        const ext = (recorder.mimeType || "audio/webm").includes("mp4")
          ? "m4a"
          : (recorder.mimeType || "").includes("ogg")
            ? "ogg"
            : "webm";

        const form = new FormData();
        form.append("audio", blob, `clip.${ext}`);

        const res = await fetch(`${API}/transcribe`, {
          method: "POST",
          body: form,
        });

        if (!res.ok) {
          let detail = `Transcription failed (${res.status})`;
          try {
            const body = await res.json();
            detail = body?.detail ?? detail;
          } catch {
            /* ignore */
          }
          throw new Error(detail);
        }

        const body = (await res.json()) as { text?: string };
        const text = (body.text ?? "").trim();

        if (!text) {
          setState("error");
          setError("No speech detected. Try again.");
          return;
        }

        onTranscript(text);
        setState("idle");
      } catch (e) {
        setState("error");
        setError(String(e));
      }
    };

    recorder.start();
    setState("recording");
  }, [onTranscript, _cleanupStream]);

  // ---- Public API ----------------------------------------------------
  const start = useCallback(async () => {
    if (state === "recording" || state === "transcribing") return;
    setError(null);
    setState("requesting");

    if (liveCapable) {
      await _startLive();
    } else {
      await _startWhisper();
    }
  }, [state, liveCapable, _startLive, _startWhisper]);

  const stop = useCallback(() => {
    if (liveCapable && recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        /* ignore */
      }
      return;
    }
    const rec = mediaRecorderRef.current;
    if (!rec || rec.state === "inactive") return;
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
  }, [liveCapable]);

  return {
    state,
    error,
    supported,
    liveCapable,
    start,
    stop,
    cancel,
  };
}

// ---------------------------------------------------------------------------
// Voice metadata — exported for the picker UI
// ---------------------------------------------------------------------------
export interface VoiceOption {
  name: string;
  lang: string;
}

const VOICE_STORAGE_KEY = "argus.tts.voice";

/**
 * Read the voices available on this machine. Some browsers need a
 * `voiceschanged` event before `getVoices()` returns non-empty.
 */
export function listVoices(): VoiceOption[] {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return [];
  }
  return window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang.startsWith("en"))
    .map((v) => ({ name: v.name, lang: v.lang }));
}

/**
 * Default voice selection when the user hasn't picked one yet.
 * Prefers named male voices, falls back to any English voice.
 */
function pickDefaultVoice(
  voices: SpeechSynthesisVoice[],
): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang.startsWith("en"));
  if (!english.length) return voices[0];

  const MALE_RE =
    /Microsoft Guy|Microsoft Davis|Microsoft Jason|Microsoft Andrew|Microsoft Brian|Alex|Daniel|Google UK English Male|Tom|Oliver|Thomas/i;

  return english.find((v) => MALE_RE.test(v.name)) ?? english[0];
}

// ---------------------------------------------------------------------------
// Text preprocessing — strip markdown + readability punctuation, then
// insert natural pauses
// ---------------------------------------------------------------------------

/**
 * Convert markdown-ish text into plain prose suitable for TTS.
 *
 * Handles the subset of markdown that Argus actually emits (via
 * react-markdown + remark-gfm): bold, italic, inline code, fenced code
 * blocks, headings, list bullets, ordered lists, links, images,
 * blockquotes, horizontal rules, strikethrough, and table pipes.
 *
 * Also normalizes word-internal `_` and `*` (filenames, snake_case) and
 * human-readability punctuation that TTS would otherwise voice literally
 * — e.g. "(s)", stray end-of-line colons, "&", "+", "/" between words.
 *
 * Order matters — multi-char patterns must run before their shorter
 * siblings (`**` before `*`, ``` ``` ``` before `` ` ``).
 */
function stripMarkdownForSpeech(text: string): string {
  let s = text;

  // ---- Redundant leading bold filename -------------------------------
  // The overview path emits "**Anas_Yaqoob_Baig_CV.pdf** Anas Yaqoob…".
  // The filename is already shown as a pill above the bubble, so reading
  // it aloud duplicates information. Strip a leading bold filename.
  s = s.replace(/^\s*\*\*[^*\n]+\.(?:pdf|txt|md|docx?)\*\*\s*/i, "");

  // ---- Decorative punctuation / readability abbreviations ------------

  // "(s)" and "(es)" are human-readability plurals — drop them so
  // "1 document(s)" reads as "1 document".
  s = s.replace(/\((?:s|es)\)/gi, "");

  // Curly quotes → straight. Both read the same to TTS, but consistency
  // makes downstream rules simpler.
  s = s.replace(/[\u2018\u2019]/g, "'");
  s = s.replace(/[\u201C\u201D]/g, '"');

  // Sentence-ending colons: the punctuation already implies a pause, so
  // turn "You have 1 document:" into "You have 1 document."
  s = s.replace(/:\s*(?=\n|$)/g, ".");

  // Common prose shorthand → spoken words.
  // Only replace "&" when it sits between word chars (R&D, R & D).
  s = s.replace(/(\w)\s*&\s*(\w)/g, "$1 and $2");
  // Trailing "++" (C++) → "plus plus" — must run before the single-plus rule.
  s = s.replace(/(\w)\+\+/g, "$1 plus plus");
  // "+" between word chars → "plus" (A+B).
  s = s.replace(/(\w)\s*\+\s*(\w)/g, "$1 plus $2");
  // "/" between word chars → " slash " for paths (CI/CD).
  s = s.replace(/(\w)\s*\/\s*(\w)/g, "$1 slash $2");

  // ---- Fenced code blocks ---------------------------------------------
  s = s.replace(/```[a-zA-Z0-9_-]*\n([\s\S]*?)```/g, (_m, body: string) => {
    return ` code sample: ${body.trim()} `;
  });

  // ---- Inline code ----------------------------------------------------
  s = s.replace(/`([^`]+)`/g, "$1");

  // ---- Images (before links) -----------------------------------------
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");

  // ---- Links ----------------------------------------------------------
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");

  // ---- Word-internal underscores/asterisks (filenames, identifiers) --
  s = s.replace(/(\w)_(\w)/g, "$1 $2");
  s = s.replace(/(\w)\*(\w)/g, "$1 $2");

  // ---- Bold (before italic) ------------------------------------------
  s = s.replace(/\*\*([^*]+)\*\*/g, "$1");
  s = s.replace(/__([^_]+)__/g, "$1");

  // ---- Italic --------------------------------------------------------
  s = s.replace(/(^|[^*\w])\*([^*\n]+?)\*(?=[^*\w]|$)/g, "$1$2");
  s = s.replace(/(^|[^_\w])_([^_\n]+?)_(?=[^_\w]|$)/g, "$1$2");

  // ---- Strikethrough -------------------------------------------------
  s = s.replace(/~~([^~]+)~~/g, "$1");

  // ---- Headings ------------------------------------------------------
  s = s.replace(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/gm, "$1.");

  // ---- Blockquotes ---------------------------------------------------
  s = s.replace(/^\s{0,3}>\s?/gm, "");

  // ---- Horizontal rules ----------------------------------------------
  s = s.replace(/^\s{0,3}([-*_])\s*(?:\1\s*){2,}$/gm, " ");

  // ---- Unordered list bullets ----------------------------------------
  s = s.replace(/^\s{0,3}[-*+]\s+/gm, "");

  // ---- Ordered list markers ------------------------------------------
  s = s.replace(/^\s{0,3}\d+\.\s+/gm, "");

  // ---- Table dividers + pipes ----------------------------------------
  s = s.replace(/^\s*\|?[\s:|-]+\|[\s:|-]+\|?\s*$/gm, "");
  s = s.replace(/\s*\|\s*/g, ", ");

  // ---- Task list checkboxes ------------------------------------------
  s = s.replace(/^\s*\[[ xX]\]\s*/gm, "");

  // ---- Stray brackets ------------------------------------------------
  s = s.replace(/\[([^\]]*)\]/g, "$1");

  return s;
}

/**
 * Insert natural pauses so the TTS engine breathes.
 * Assumes the input is already plain prose (markdown stripped).
 */
function addNaturalPauses(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/\.\.\./g, ", ")
    .replace(/[—–]/g, ", ")
    .replace(/;\s*/g, ", ")
    .replace(
      /(\b\w+(?:\s+\w+){8,})\s+(and|but|so|however|therefore)\b/g,
      "$1, $2",
    )
    .replace(/([.!?])\s+(?=[A-Z])/g, "$1  ")
    .replace(/[_*`~|<>#]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Full pipeline: markdown → plain prose → natural pauses. */
function prepareForSpeech(text: string): string {
  return addNaturalPauses(stripMarkdownForSpeech(text));
}

// ---------------------------------------------------------------------------
// useSpeech — user-selectable voice, per-message + preview playback
// ---------------------------------------------------------------------------
interface SpeechApi {
  speaking: boolean;
  speakingKey: string | null;
  speak: (key: string, text: string) => void;
  stop: () => void;
  toggle: (key: string, text: string) => void;
  supported: boolean;
  voiceName: string | null;
  setVoiceName: (name: string) => void;
  availableVoices: VoiceOption[];
  preview: () => void;
  previewing: boolean;
}

const PREVIEW_KEY = "__preview__";
const PREVIEW_SAMPLE =
  "This is a preview of the selected voice for Argus document answers.";

export function useSpeech(): SpeechApi {
  const [speakingKey, setSpeakingKey] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [voiceName, setVoiceNameState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(VOICE_STORAGE_KEY);
    } catch {
      return null;
    }
  });
  const [availableVoices, setAvailableVoices] = useState<VoiceOption[]>([]);

  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const supported =
    typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => {
    if (!supported) return;

    const refresh = () => setAvailableVoices(listVoices());
    refresh();

    window.speechSynthesis.addEventListener("voiceschanged", refresh);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", refresh);
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
    };
  }, [supported]);

  const setVoiceName = useCallback((name: string) => {
    setVoiceNameState(name);
    try {
      localStorage.setItem(VOICE_STORAGE_KEY, name);
    } catch {
      /* ignore */
    }
  }, []);

  const _resolveVoice = useCallback((): SpeechSynthesisVoice | null => {
    if (!supported) return null;
    const all = window.speechSynthesis.getVoices();
    if (voiceName) {
      const match = all.find((v) => v.name === voiceName);
      if (match) return match;
    }
    return pickDefaultVoice(all);
  }, [supported, voiceName]);

  const _cancelAll = useCallback(() => {
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* ignore */
    }
    utteranceRef.current = null;
  }, []);

  const stop = useCallback(() => {
    if (!supported) return;
    _cancelAll();
    setSpeakingKey(null);
    setPreviewing(false);
  }, [supported, _cancelAll]);

  const speak = useCallback(
    (key: string, text: string) => {
      if (!supported) return;
      const raw = (text ?? "").trim();
      if (!raw) return;

      _cancelAll();
      setPreviewing(false);

      const spoken = prepareForSpeech(raw);
      const voice = _resolveVoice();

      // Warm-up utterance primes the engine so the rate property is
      // applied from the first syllable (Chromium bug workaround).
      const warmup = new SpeechSynthesisUtterance(" ");
      warmup.rate = 0.92;
      warmup.pitch = 0.95;
      warmup.volume = 0;
      if (voice) warmup.voice = voice;
      window.speechSynthesis.speak(warmup);

      const utt = new SpeechSynthesisUtterance(spoken);
      utt.rate = 0.92;
      utt.pitch = 0.95;
      utt.volume = 1.0;
      if (voice) utt.voice = voice;

      utt.onend = () => setSpeakingKey(null);
      utt.onerror = () => setSpeakingKey(null);

      utteranceRef.current = utt;
      setSpeakingKey(key);
      window.speechSynthesis.speak(utt);
    },
    [supported, _resolveVoice, _cancelAll],
  );

  const toggle = useCallback(
    (key: string, text: string) => {
      if (speakingKey === key) stop();
      else speak(key, text);
    },
    [speakingKey, speak, stop],
  );

  const preview = useCallback(() => {
    if (!supported) return;

    if (previewing) {
      _cancelAll();
      setPreviewing(false);
      setSpeakingKey(null);
      return;
    }

    _cancelAll();

    const voice = _resolveVoice();
    const utt = new SpeechSynthesisUtterance(PREVIEW_SAMPLE);
    utt.rate = 0.92;
    utt.pitch = 0.95;
    utt.volume = 1.0;
    if (voice) utt.voice = voice;

    utt.onend = () => {
      setPreviewing(false);
      setSpeakingKey(null);
    };
    utt.onerror = () => {
      setPreviewing(false);
      setSpeakingKey(null);
    };

    utteranceRef.current = utt;
    setPreviewing(true);
    setSpeakingKey(PREVIEW_KEY);
    window.speechSynthesis.speak(utt);
  }, [supported, previewing, _resolveVoice, _cancelAll]);

  return {
    speaking: speakingKey !== null,
    speakingKey,
    speak,
    stop,
    toggle,
    supported,
    voiceName,
    setVoiceName,
    availableVoices,
    preview,
    previewing,
  };
}