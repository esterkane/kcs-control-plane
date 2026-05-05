type BadgeTone = "default" | "success" | "warning" | "neutral" | "accent";

type BadgeProps = {
  children: string;
  tone?: BadgeTone;
};

export function Badge({ children, tone = "default" }: BadgeProps) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
