import DOMPurify from "dompurify";
import { marked } from "marked";

const ALLOWED_TAGS = [
  "p",
  "br",
  "strong",
  "em",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "a",
  "blockquote",
  "h1",
  "h2",
  "h3",
  "h4",
];

const ALLOWED_ATTR = ["href", "title"];

marked.setOptions({ breaks: true, gfm: true });

export function renderMarkdown(src: string): string {
  const html = marked.parse(src) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORBID_ATTR: ["style", "onerror", "onload"],
  });
}
