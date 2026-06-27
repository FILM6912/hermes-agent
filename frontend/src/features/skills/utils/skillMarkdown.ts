/** Strip YAML frontmatter from SKILL.md content. */

export function stripSkillFrontmatter(content: string): {
  frontmatter: string | null;
  body: string;
} {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(content || "");
  if (!match) {
    return { frontmatter: null, body: content || "" };
  }
  return {
    frontmatter: match[1],
    body: content.slice(match[0].length),
  };
}
