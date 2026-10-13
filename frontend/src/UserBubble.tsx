interface UserBubbleProps {
  text: string;
}

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className="argus-user-row">
      <div className="argus-user-bubble">{text}</div>
    </div>
  );
}