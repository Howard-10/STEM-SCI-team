import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type RichMarkdownProps = {
  content: string;
  className?: string;
};

export function RichMarkdown({ content, className = "" }: RichMarkdownProps) {
  return (
    <div className={`rich-markdown ${className}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer" />
          ),
          img: ({ node: _node, ...props }) => (
            <img {...props} loading="eager" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
