import * as api from "@/api";

let cache: Map<string, api.ToolInfo> | null = null;
let inflight: Promise<Map<string, api.ToolInfo>> | null = null;

export async function loadTools(): Promise<Map<string, api.ToolInfo>> {
  if (cache) return cache;
  if (inflight) return inflight;
  inflight = api
    .getTools()
    .then((tools) => {
      cache = new Map(tools.map((t) => [t.name, t]));
      return cache;
    })
    .catch(() => {
      cache = new Map();
      return cache;
    });
  return inflight;
}

export function getTool(name: string): api.ToolInfo | undefined {
  return cache?.get(name);
}
