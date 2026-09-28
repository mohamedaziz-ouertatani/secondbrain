/**
 * rehype plugin: split each answer block into claims, each ending at its citation run.
 * "A is B [1]. C is D [2][3]." → <span class="claim" data-cites="1">A is B [1].</span>
 *                                <span class="claim" data-cites="2,3"> C is D [2][3].</span>
 * Lets a fiche light exactly the sentences that lean on it, and anchor margin tabs per claim.
 */

type Node = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: Node[];
};

const BLOCKS = new Set(["p", "li", "h1", "h2", "h3", "h4", "td"]);

function citeNumber(n: Node | undefined): number | null {
  if (n?.type !== "element" || n.tagName !== "a") return null;
  const m = /^#cite-(\d+)$/.exec(String(n.properties?.href ?? ""));
  return m ? Number(m[1]) : null;
}

const isBlank = (n: Node | undefined) => n?.type === "text" && /^\s*$/.test(n.value ?? "");

function claimsOf(children: Node[]): Node[] {
  const out: Node[] = [];
  let buf: Node[] = [];
  let cites: number[] = [];
  const flush = () => {
    if (!buf.length) return;
    out.push({
      type: "element",
      tagName: "span",
      properties: { className: ["claim"], dataCites: cites.join(",") },
      children: buf,
    });
    buf = [];
    cites = [];
  };
  for (let i = 0; i < children.length; i++) {
    const c = children[i];
    const n = citeNumber(c);
    buf.push(c);
    if (n === null) continue;
    if (!cites.includes(n)) cites.push(n);
    const next = children[i + 1];
    if (citeNumber(next) !== null) continue; // [1][2]
    if (isBlank(next) && citeNumber(children[i + 2]) !== null) {
      buf.push(next); // [1] [2]
      i++;
      continue;
    }
    if (next?.type === "text") {
      const punct = /^[.,;:!?؟،)]+/.exec(next.value ?? ""); // the claim keeps its closing punctuation
      if (punct) {
        buf.push({ type: "text", value: punct[0] });
        next.value = (next.value ?? "").slice(punct[0].length);
      }
    }
    flush();
  }
  flush();
  return out;
}

function hasCite(nodes: Node[] = []): boolean {
  return nodes.some((n) => citeNumber(n) !== null);
}

export function rehypeClaims() {
  const walk = (node: Node) => {
    if (node.type === "element" && BLOCKS.has(node.tagName ?? "") && hasCite(node.children)) {
      node.children = claimsOf(node.children ?? []);
      return;
    }
    node.children?.forEach(walk);
  };
  return (tree: Node) => walk(tree);
}
