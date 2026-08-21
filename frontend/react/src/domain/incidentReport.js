export function simpleIncidentReport(content) {
  const text = String(content || "").replace(/\r/g, "").trim();
  if (!text) return "No report content is available.";
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const field = (label) => {
    const line = lines.find((item) => item.toLowerCase().startsWith(`${label.toLowerCase()}:`));
    return line ? line.slice(line.indexOf(":") + 1).trim() : "";
  };
  const section = (names) => {
    const headings = names.map((name) => name.toLowerCase());
    const start = lines.findIndex((line) => headings.some((name) => line.replace(/^#+\s*/, "").toLowerCase().includes(name)));
    if (start < 0) return "";
    const values = [];
    for (let index = start + 1; index < lines.length; index += 1) {
      if (/^#+\s+/.test(lines[index])) break;
      values.push(lines[index].replace(/^[-*]\s*/, ""));
      if (values.join(" ").length >= 280) break;
    }
    return values.join(" ").slice(0, 320);
  };
  const title = lines.find((line) => /^#\s+/.test(line))?.replace(/^#+\s*/, "") || "Incident report";
  const rows = [
    ["Incident", field("Incident ID") || field("Incident reference")],
    ["Jira", field("Jira ticket")],
    ["Service", field("Service")],
    ["Severity", field("Severity")],
    ["Root cause", section(["root cause"]) || field("Root cause") || field("Probable root cause")],
    ["Impact", section(["technical and business impact", "impact"]) || field("Impact")],
    ["Recommended action", section(["resolution procedure", "recommended response"]) || field("Recommended action") || field("Immediate action")],
  ].filter(([, value]) => value);
  return [`# ${title}`, ...rows.map(([label, value]) => `${label}: ${value}`)].join("\n\n");
}


export function incidentDraftHasSubstantiveContent(content) {
  const body = String(content || "")
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/^\s*#+\s*/, "").trim())
    .filter((line) => line && !/^incident (report|record)$/i.test(line))
    .join(" ");
  return body.length >= 40;
}
