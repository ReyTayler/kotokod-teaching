interface Props { name: string; size?: number; }

export function Avatar({ name, size = 32 }: Props) {
  const parts = name.trim().split(/\s+/);
  const initials = (parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className="avatar"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.38),
        background: `hsl(${hue},55%,92%)`,
        border: `2px solid hsl(${hue},50%,80%)`,
        color: `hsl(${hue},55%,35%)`,
      }}
    >
      {initials}
    </div>
  );
}
