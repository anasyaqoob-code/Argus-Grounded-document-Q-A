/** Argus brand mark and utility SVG icons. */

import React from "react";

export const TRANSPARENT_AVATAR =
  "data:image/png;base64," +
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

// ---------------------------------------------------------------------------
// Thumbs up — feedback (helpful)
// ---------------------------------------------------------------------------
export function ThumbsUpIcon({
  size = 14,
  color = "currentColor",
  filled = false,
  idSuffix = "tu",
}: {
  size?: number;
  color?: string;
  filled?: boolean;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = filled ? `url(#${gradId})` : color;
  const fill = filled ? `url(#${gradId})` : "none";
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke={stroke}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#A855F7" />
          <stop offset="100%" stopColor="#EC4899" />
        </linearGradient>
      </defs>
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Thumbs down — feedback (not helpful)
// ---------------------------------------------------------------------------
export function ThumbsDownIcon({
  size = 14,
  color = "currentColor",
  filled = false,
  idSuffix = "td",
}: {
  size?: number;
  color?: string;
  filled?: boolean;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = filled ? `url(#${gradId})` : color;
  const fill = filled ? `url(#${gradId})` : "none";
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke={stroke}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#A855F7" />
          <stop offset="100%" stopColor="#EC4899" />
        </linearGradient>
      </defs>
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Shared helper: build a gradient def id per instance.
// ---------------------------------------------------------------------------
const ARGUS_STOPS = (
  <>
    <stop offset="0%" stopColor="#A855F7" />
    <stop offset="100%" stopColor="#EC4899" />
  </>
);

// ---------------------------------------------------------------------------
// Argus brand mark
// ---------------------------------------------------------------------------
interface ArgusLogoProps {
  size?: number;
  color?: string;
  idSuffix?: string;
}

export function ArgusLogo({
  size = 24,
  color,
  idSuffix = "main",
}: ArgusLogoProps) {
  const gradId = `argus-grad-${idSuffix}`;
  const stroke = color ?? `url(#${gradId})`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ verticalAlign: "middle", display: "inline-block" }}
    >
      <defs>
        <linearGradient
          id={gradId}
          x1="0"
          y1="0"
          x2="32"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <path d="M16 4 L20 9 L16 14 L12 9 Z" stroke={stroke} />
      <path d="M4 26 L10 18 L14 22" stroke={stroke} />
      <path d="M28 26 L22 18 L18 22" stroke={stroke} />
      <path d="M6 26 L26 26" stroke={stroke} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Pencil — rename affordance
// ---------------------------------------------------------------------------
export function PencilIcon({
  size = 13,
  color = "currentColor",
}: {
  size?: number;
  color?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Trash — delete affordance
// ---------------------------------------------------------------------------
export function TrashIcon({
  size = 13,
  color = "currentColor",
}: {
  size?: number;
  color?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Gear — settings affordance
// ---------------------------------------------------------------------------
export function GearIcon({
  size = 13,
  color = "currentColor",
}: {
  size?: number;
  color?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <circle cx="12" cy="12" r="3" />
      <path
        d={
          "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 " +
          "2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 " +
          "1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09" +
          "A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06" +
          "a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 " +
          ".33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 " +
          "2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82" +
          "l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06" +
          "a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3" +
          "a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 " +
          "1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 " +
          "2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9" +
          "a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09" +
          "a1.65 1.65 0 0 0-1.51 1z"
        }
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Mic — voice input (brand gradient)
// ---------------------------------------------------------------------------
export function MicIcon({
  size = 16,
  idSuffix = "mic",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = `url(#${gradId})`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <rect x="9" y="2" width="6" height="12" rx="3" stroke={stroke} />
      <path d="M5 11a7 7 0 0 0 14 0" stroke={stroke} />
      <line x1="12" y1="18" x2="12" y2="22" stroke={stroke} />
      <line x1="8" y1="22" x2="16" y2="22" stroke={stroke} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Stop — square, shown while recording (brand gradient)
// ---------------------------------------------------------------------------
export function StopIcon({
  size = 16,
  idSuffix = "stop",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <rect x="6" y="6" width="12" height="12" rx="2" fill={`url(#${gradId})`} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Speaker — read answer aloud (brand gradient)
// ---------------------------------------------------------------------------
export function SpeakerIcon({
  size = 14,
  idSuffix = "speaker",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = `url(#${gradId})`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" stroke={stroke} />
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" stroke={stroke} />
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" stroke={stroke} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Muted — stop reading (brand gradient)
// ---------------------------------------------------------------------------
export function MutedIcon({
  size = 14,
  idSuffix = "muted",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = `url(#${gradId})`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" stroke={stroke} />
      <line x1="22" y1="9" x2="16" y2="15" stroke={stroke} />
      <line x1="16" y1="9" x2="22" y2="15" stroke={stroke} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Regenerate — circular arrows (brand gradient), for icon-only action button
// ---------------------------------------------------------------------------
export function RegenerateIcon({
  size = 14,
  idSuffix = "regen",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = `url(#${gradId})`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <path d="M3 12a9 9 0 0 1 15.5-6.2" stroke={stroke} />
      <path d="M21 12a9 9 0 0 1-15.5 6.2" stroke={stroke} />
      <polyline points="18.5 3.5 18.5 6.5 15.5 6.5" stroke={stroke} />
      <polyline points="5.5 20.5 5.5 17.5 8.5 17.5" stroke={stroke} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Export — download arrow into tray (brand gradient)
// ---------------------------------------------------------------------------
export function ExportIcon({
  size = 14,
  idSuffix = "export",
}: {
  size?: number;
  idSuffix?: string;
}) {
  const gradId = `argus-icon-grad-${idSuffix}`;
  const stroke = `url(#${gradId})`;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          {ARGUS_STOPS}
        </linearGradient>
      </defs>
      <path d="M12 3v12" stroke={stroke} />
      <polyline points="8 11 12 15 16 11" stroke={stroke} />
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke={stroke} />
    </svg>
  );
}

export default ArgusLogo;