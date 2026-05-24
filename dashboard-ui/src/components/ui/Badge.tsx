import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "info" | "warn" | "danger" | "profit" | "loss";

const TONE: Record<Tone, string> = {
  neutral: "bg-bg-3 text-text-secondary border-border",
  info: "bg-info/10 text-info border-info/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  danger: "bg-danger/10 text-danger border-danger/30",
  profit: "bg-profit/10 text-profit border-profit/30",
  loss: "bg-loss/10 text-loss border-loss/30",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5",
        "text-[11px] font-medium leading-none uppercase tracking-wide",
        TONE[tone],
        className,
      )}
      {...props}
    />
  );
}
