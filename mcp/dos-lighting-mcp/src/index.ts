import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { promisify } from "node:util";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const execFileAsync = promisify(execFile);
const PROJECT_ROOT = resolve(process.env.DOS_LIGHTING_PROJECT_ROOT ?? join(import.meta.dirname, "..", "..", ".."));
const PORTABLE_NPM = join(PROJECT_ROOT, ".tools", "node-v20.19.5-win-x64", "npm.cmd");
const NPM_COMMAND = existsSync(PORTABLE_NPM) ? PORTABLE_NPM : "npm";

const text = (value: string) => ({
  content: [{ type: "text" as const, text: value }]
});

const jsonText = (value: unknown) => text(JSON.stringify(value, null, 2));

async function readIfExists(path: string): Promise<string> {
  try {
    return await readFile(path, "utf8");
  } catch {
    return "";
  }
}

async function listFilesSafe(path: string): Promise<string[]> {
  try {
    const entries = await readdir(path, { withFileTypes: true });
    return entries.filter((entry) => entry.isFile()).map((entry) => entry.name).sort();
  } catch {
    return [];
  }
}

async function pathStatus(relativePath: string): Promise<{ path: string; exists: boolean; kind: string | null }> {
  const fullPath = join(PROJECT_ROOT, relativePath);
  try {
    const info = await stat(fullPath);
    return {
      path: relativePath,
      exists: true,
      kind: info.isDirectory() ? "directory" : "file"
    };
  } catch {
    return { path: relativePath, exists: false, kind: null };
  }
}

async function databaseSchemaSummary(): Promise<string> {
  const databaseDir = join(PROJECT_ROOT, "database");
  const files = await listFilesSafe(databaseDir);
  const statements: string[] = [];

  for (const file of files.filter((item) => item.endsWith(".sql"))) {
    const sql = await readIfExists(join(databaseDir, file));
    const tables = [...sql.matchAll(/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)/gi)].map(
      (match) => match[1]
    );
    const alters = [...sql.matchAll(/ALTER\s+TABLE\s+([a-zA-Z0-9_]+)/gi)].map((match) => match[1]);
    statements.push(
      `- ${file}: tables=${tables.length ? tables.join(", ") : "none"}, alters=${alters.length ? [...new Set(alters)].join(", ") : "none"}`
    );
  }

  return statements.length ? statements.join("\n") : "No SQL migrations were found in database/.";
}

function apiContracts(): string {
  return [
    "- GET /actuator/health",
    "- POST /api/recomendaciones/resolver",
    "- GET /api/v1/modelos-vehiculo/:modeloId/decision-sistema-optico",
    "- GET /api/chat/health",
    "- POST /api/chat/message",
    "- Public catalog/admin endpoints remain owned by backend-ts route modules."
  ].join("\n");
}

function recommendationFlow(): string {
  return [
    "1. Validate request DTO at the HTTP edge.",
    "2. Load vehicle model and validate selected year.",
    "3. Load active driving profiles and tint.",
    "4. Decide or validate optical system when multiple compatibilities apply.",
    "5. Load generation/model-year compatibilities.",
    "6. Load compatible LED products by casquillo, position, and optical system.",
    "7. Score candidates by driving profile, tint, gama, lumens, and deterministic tie-breakers.",
    "8. Persist consultation through the repository/unit-of-work adapter.",
    "9. Return the existing recommendation response contract."
  ].join("\n");
}

function chatbotFlow(): string {
  return [
    "1. Frontend sends sessionId and message to POST /api/chat/message.",
    "2. FastAPI gets or creates an in-memory session with TTL.",
    "3. ChatService chooses OpenAI orchestration when configured or guided fallback otherwise.",
    "4. Tools call backend-ts for catalogs, optical decision, recommendation, gamas, and product detail.",
    "5. Backend-ts remains the source of truth; chatbot never invents recommendations.",
    "6. Response includes replyText, quickReplies, missingFields, recommendation, and resetSession."
  ].join("\n");
}

function verificationCommands(): string {
  return [
    "backend-ts: npm run lint && npm test && npm run build",
    "chatbot-python: .\\.venv\\Scripts\\python.exe -m pytest",
    "frontend: npm test && npm run build",
    "smoke: backend health, chatbot health, POST /api/recomendaciones/resolver, POST /api/chat/message"
  ].join("\n");
}

async function projectHealth() {
  const paths = await Promise.all([
    pathStatus("backend-ts/package.json"),
    pathStatus("backend-ts/src/recommendation"),
    pathStatus("chatbot-python/pyproject.toml"),
    pathStatus("chatbot-python/app/application"),
    pathStatus("frontend/package.json"),
    pathStatus("database"),
    pathStatus("mcp/dos-lighting-mcp/package.json")
  ]);

  return {
    projectRoot: PROJECT_ROOT,
    paths,
    portableNode: existsSync(join(PROJECT_ROOT, ".tools", "node-v20.19.5-win-x64", "node.exe")),
    hasEnvExample: existsSync(join(PROJECT_ROOT, ".env.example"))
  };
}

const safeVerificationCommands = {
  "backend-lint": {
    cwd: join(PROJECT_ROOT, "backend-ts"),
    command: NPM_COMMAND,
    args: ["run", "lint"]
  },
  "backend-test": {
    cwd: join(PROJECT_ROOT, "backend-ts"),
    command: NPM_COMMAND,
    args: ["test"]
  },
  "chatbot-test": {
    cwd: join(PROJECT_ROOT, "chatbot-python"),
    command: join(PROJECT_ROOT, "chatbot-python", ".venv", "Scripts", "python.exe"),
    args: ["-m", "pytest"]
  },
  "frontend-test": {
    cwd: join(PROJECT_ROOT, "frontend"),
    command: NPM_COMMAND,
    args: ["test"]
  }
} as const;

async function runSafeVerification(target: keyof typeof safeVerificationCommands) {
  const command = safeVerificationCommands[target];
  const { stdout, stderr } = await execFileAsync(command.command, command.args, {
    cwd: command.cwd,
    timeout: 120_000,
    windowsHide: true,
    maxBuffer: 1024 * 1024
  });
  return { target, stdout, stderr };
}

const server = new McpServer({
  name: "dos-lighting-mcp",
  version: "0.1.0"
});

server.resource("architecture-overview", "dos://architecture/overview", async (uri) => ({
  contents: [
    {
      uri: uri.href,
      mimeType: "text/markdown",
      text: [
        "# DOS Lighting Architecture",
        "Backend-ts and chatbot-python are migrating incrementally to hexagonal architecture.",
        "Domain and application layers must stay framework-free. Express, FastAPI, pg, httpx, OpenAI SDK, and env config belong in adapters."
      ].join("\n")
    }
  ]
}));

server.resource("db-schema", "dos://db/schema", async (uri) => ({
  contents: [{ uri: uri.href, mimeType: "text/markdown", text: await databaseSchemaSummary() }]
}));

server.resource("api-endpoints", "dos://api/endpoints", async (uri) => ({
  contents: [{ uri: uri.href, mimeType: "text/markdown", text: apiContracts() }]
}));

server.resource("recommendation-rules", "dos://recommendation/rules", async (uri) => ({
  contents: [{ uri: uri.href, mimeType: "text/markdown", text: recommendationFlow() }]
}));

server.resource("chatbot-flow", "dos://chatbot/flow", async (uri) => ({
  contents: [{ uri: uri.href, mimeType: "text/markdown", text: chatbotFlow() }]
}));

server.resource("verification-commands", "dos://verification/commands", async (uri) => ({
  contents: [{ uri: uri.href, mimeType: "text/markdown", text: verificationCommands() }]
}));

server.tool("inspect_project_health", {}, async () => jsonText(await projectHealth()));

server.tool("list_api_contracts", {}, async () => text(apiContracts()));

server.tool("get_recommendation_flow", {}, async () => text(recommendationFlow()));

server.tool("get_database_schema_summary", {}, async () => text(await databaseSchemaSummary()));

server.tool(
  "run_safe_verification",
  {
    target: z.enum(["backend-lint", "backend-test", "chatbot-test", "frontend-test"])
  },
  async ({ target }) => jsonText(await runSafeVerification(target))
);

server.prompt("refactor-to-hexagonal", { area: z.string().optional() }, ({ area }) => ({
  messages: [
    {
      role: "user",
      content: {
        type: "text",
        text: `Refactor ${area ?? "the selected DOS Lighting slice"} toward hexagonal architecture while preserving public contracts and adding use-case tests.`
      }
    }
  ]
}));

server.prompt("explain-recommendation-flow", {}, () => ({
  messages: [
    {
      role: "user",
      content: {
        type: "text",
        text: "Explain the DOS Lighting recommendation flow from HTTP request to scored products in concise Spanish."
      }
    }
  ]
}));

server.prompt("add-feature-safely", { feature: z.string().optional() }, ({ feature }) => ({
  messages: [
    {
      role: "user",
      content: {
        type: "text",
        text: `Add ${feature ?? "a new feature"} to DOS Lighting without breaking existing endpoints, DTOs, chatbot fallback, or recommendation behavior.`
      }
    }
  ]
}));

server.prompt("review-boundaries", {}, () => ({
  messages: [
    {
      role: "user",
      content: {
        type: "text",
        text: "Review DOS Lighting layer boundaries and report any domain/application imports from frameworks, SDKs, database clients, HTTP clients, or env config."
      }
    }
  ]
}));

await server.connect(new StdioServerTransport());
