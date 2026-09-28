/** The semester's modules, grouped by teaching unit (UE). A UE owns one bristol tint. */

export type Unit = { id: string; name: string };

export const UNITS: Unit[] = [
  { id: "modeling", name: "Data Modeling" },
  { id: "random", name: "Random Models and Optimisation" },
  { id: "processing", name: "Data Processing" },
  { id: "sustainable", name: "Sustainable Development" },
  { id: "pro", name: "Preparation for professional life" },
  { id: "seminars", name: "Séminaires" },
];

const MODULES: Record<string, { unit: string; code: string }> = {
  "Advanced Deep Learning": { unit: "modeling", code: "ADL" },
  "Big Data Analytics": { unit: "modeling", code: "BDA" },
  DEVOPS: { unit: "modeling", code: "DEVOPS" },
  "Optimization for ML": { unit: "random", code: "OPTML" },
  "Probability 2": { unit: "random", code: "PROB2" },
  "Advanced Data Science project": { unit: "processing", code: "ADSP" },
  CSR: { unit: "sustainable", code: "CSR" },
  SDG: { unit: "sustainable", code: "SDG" },
  "Personnal Skills F": { unit: "pro", code: "PSK·F" },
  "Personnal Skills A": { unit: "pro", code: "PSK·A" },
  "AWS Fundamentals": { unit: "seminars", code: "AWS" },
  "Certification en Blockchain": { unit: "seminars", code: "BCHAIN" },
};

export const OTHER_UNIT: Unit = { id: "other", name: "Other drawers" };

/** Every known module of a unit, including ones with nothing synced yet. */
export function modulesOf(unitId: string): string[] {
  return Object.entries(MODULES)
    .filter(([, m]) => m.unit === unitId)
    .map(([name]) => name);
}

export function isKnownModule(course: string): boolean {
  return course in MODULES;
}

export function unitOf(course: string | null): Unit {
  const id = course ? MODULES[course]?.unit : undefined;
  return UNITS.find((u) => u.id === id) ?? OTHER_UNIT;
}

/** CSS custom property value for a course's bristol tint. */
export function tintVar(course: string | null): string {
  return `var(--tint-${unitOf(course).id})`;
}

export function moduleCode(course: string | null): string {
  if (!course) return "NOTE";
  const known = MODULES[course]?.code;
  if (known) return known;
  const words = course.split(/[\s_-]+/).filter(Boolean);
  return (words.length === 1 ? course.slice(0, 6) : words.map((w) => w[0]).join("")).toUpperCase();
}

/** "CH1", "S3" or "WS2" from the Blackboard folder path, when the material says so. */
export function chapterCode(path: string | undefined): string | null {
  for (const seg of (path ?? "").split("/").slice(1, -1)) {
    const ch = /\bchap(?:ter|itre)?\s*[-:]?\s*(\d+)/i.exec(seg);
    if (ch) return `CH${ch[1]}`;
    const s = /^S(\d+)\b/.exec(seg);
    if (s) return `S${s[1]}`;
    const ws = /\bworkshop\s*(\d+)/i.exec(seg);
    if (ws) return `WS${ws[1]}`;
  }
  return null;
}

/** Folder path inside the module, used as the drawer's guide cards. */
export function folderOf(path: string): string {
  const parts = path.split("/");
  return parts.slice(1, -1).join(" › ");
}
