/**
 * Prepare model output and synced notes for react-markdown:
 * normalise LaTeX delimiters to $…$ / $$…$$ (remark-math) and turn [n] citations into #cite-n links.
 */
export function prepareAnswer(text: string): string {
  return normaliseMath(text).replace(/(?<![\\$])\[(\d+)\](?!\()/g, "[$1](#cite-$1)");
}

export function normaliseMath(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => `$$${m}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => `$${m.trim()}$`);
}

/**
 * A short plain-text excerpt of a passage: drops Markdown headings, images and the synced-note
 * breadcrumb line (*Course › Folder*), strips emphasis markers, keeps LaTeX as written.
 */
export function excerpt(text: string, max = 240): string {
  const body = text
    .split("\n")
    .filter((line) => !/^\s*#{1,6}\s/.test(line) && !/^\s*\*[^*].*›.*\*\s*$/.test(line))
    .join(" ")
    .replace(/!\[[^\]]*\]\((<[^>]*>|[^)]*)\)/g, "")
    .replace(/\*\*|__|`/g, "")
    .replace(/(^|\s)[*_](\S)/g, "$1$2")
    .replace(/(\S)[*_](?=\s|$)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  return body.length <= max ? body : `${body.slice(0, max).replace(/\s+\S*$/, "")}…`;
}

/**
 * Drop a synced note's leading "# Title" and its "*Course › Folder*" breadcrumb when the page
 * already shows title and provenance.
 */
export function withoutLeadingTitle(md: string): string {
  return md.replace(/^\s*#\s[^\n]*\n+/, "").replace(/^\s*\*[^*\n]*›[^*\n]*\*\s*\n+/, "");
}

/**
 * A note's image reference as a URL-encoded path relative to the note, or null when it names a
 * scheme (web, data:, javascript:…) rather than a file beside the note.
 */
export function relativeImagePath(src: string): string | null {
  if (/^[a-z][a-z0-9+.-]*:/i.test(src) || src.startsWith("//")) return null;
  let path = src;
  try {
    path = decodeURIComponent(src);
  } catch {
    // a stray % stays as written
  }
  return path.split("/").map(encodeURIComponent).join("/");
}
