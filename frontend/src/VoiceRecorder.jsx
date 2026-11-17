import React, { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

const RECORDING_LIMIT_MS = 29000;

export default function VoiceRecorder({ conversation, disabled, onTranscript, onError, onActive, onPhaseChange }) {
  const active = useRef(null);
  const [phase, setPhase] = useState("idle");
  useEffect(() => { onPhaseChange?.(phase); }, [phase, onPhaseChange]);

  useEffect(() => () => {
    const job = active.current;
    active.current = null;
    if (!job) return;
    clearTimeout(job.timer);
    job.abort.abort();
    if (job.recorder?.state === "recording") job.recorder.stop();
    job.stream?.getTracks().forEach((track) => track.stop());
    onActive(false);
    onPhaseChange?.("idle");
  }, []);

  async function record() {
    if (active.current) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      onError("Mikrofon memerlukan HTTPS dan browser yang mendukung perekaman.");
      return;
    }
    const job = { abort: new AbortController() };
    active.current = job;
    onError("");
    onActive(true);
    setPhase("permission");
    function finish() {
      clearTimeout(job.timer);
      job.stream?.getTracks().forEach((track) => track.stop());
      if (active.current !== job) return;
      active.current = null;
      setPhase("idle");
      onActive(false);
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      job.stream = stream;
      if (active.current !== job) {
        finish();
        return;
      }
      const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      job.recorder = recorder;
      const chunks = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => {
        if (active.current === job) onError("Rekaman gagal. Coba lagi.");
        finish();
      };
      recorder.onstop = async () => {
        clearTimeout(job.timer);
        stream.getTracks().forEach((track) => track.stop());
        if (active.current !== job) return;
        setPhase("transcribing");
        try {
          const audio = new Blob(chunks, { type: recorder.mimeType || chunks[0]?.type });
          if (!audio.size) throw Error("Rekam ucapan sebelum berhenti.");
          const response = await fetch(`/web/chat/conversations/${conversation}/voice/transcribe`, {
            method: "POST", body: audio, signal: job.abort.signal, credentials: "same-origin",
          });
          const result = await response.json().catch(() => ({}));
          if (!response.ok) throw Error(result.detail || "Transkripsi gagal. Coba lagi.");
          if (active.current === job) onTranscript(result.text);
        } catch (error) {
          if (active.current === job) onError(error.message);
        } finally {
          finish();
        }
      };
      recorder.start();
      if (active.current !== job) return;
      setPhase("recording");
      job.timer = setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, RECORDING_LIMIT_MS);
    } catch (error) {
      if (active.current === job) {
        onError(error.name === "NotAllowedError" ? "Izinkan akses mikrofon di browser." : "Mikrofon tidak bisa digunakan.");
      }
      finish();
    }
  }

  if (phase === "recording") {
    return <button type="button" className="chat-icon chat-voice-recording" aria-label="Berhenti merekam" title="Berhenti merekam" onClick={() => {
      if (active.current?.recorder?.state === "recording") active.current.recorder.stop();
    }}><Square size={16} aria-hidden="true" /></button>;
  }
  const label = phase === "transcribing" ? "Mentranskripsi…" : phase === "permission" ? "Menunggu mikrofon…" : "Rekam suara";
  return <button type="button" className="chat-icon" aria-label={label} title={label}
    onClick={record} disabled={disabled || phase !== "idle"}>
    <Mic size={16} aria-hidden="true" />
    {phase !== "idle" && <span role="status" className="chat-visually-hidden">{label}</span>}
  </button>;
}
