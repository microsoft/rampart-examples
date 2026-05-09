import { renderMarkdown } from "@/lib/markdown";

interface Props {
  content: string;
}

export function UserMessage({ content }: Props) {
  const html = renderMarkdown(content);
  return (
    <div className="flex justify-end">
      <div
        className="markdown max-w-[80%] rounded-2xl rounded-tr-sm bg-bubble-user px-4 py-2 text-base text-bubble-user-fg"
        data-testid="user-message"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitized by DOMPurify in lib/markdown.ts
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
