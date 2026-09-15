#!/usr/bin/env node
// @ts-check
/**
 * file-lease.mjs — makes Claude Code agents take turns on a file.
 *
 * Parallel agents that edit the same file overwrite each other's intent even
 * when no single write is lost: agent A reads, agent B rewrites the function,
 * agent A applies an edit planned against code that no longer exists. Claude
 * Code's "modified since read" check catches a stale byte-level write; it does
 * not stop two agents from both believing they own the file.
 *
 * One Claude Code hook, dispatched on hook_event_name:
 *   PreToolUse (Edit|Write|MultiEdit|NotebookEdit) → take or refresh the lease,
 *                                                     or deny with who holds it
 *   SubagentStop → release that subagent's leases
 *   Stop         → release the main thread's leases (its turn is over)
 *   SessionEnd   → release everything the session held
 *
 * A holder is session_id plus agent_id ("main" on the main thread). A lease
 * nobody has touched for FILE_LEASE_TTL_MS (default 5 minutes) is free again,
 * so a crashed agent cannot hold a file forever.
 *
 * The main thread's lease yields to its own subagents. The main thread is the
 * one that delegated; a foreground subagent it is waiting on would otherwise
 * be denied until the TTL ran out, with the main thread unable to reach Stop.
 *
 * Fails open. A lock that breaks editing when its own state is unreadable is a
 * worse defect than the overlap it exists to prevent, so every error allows.
 *
 * Plain Node ESM with no dependencies, because it runs in every repo the
 * gauntlet arms, on whatever machine opens that repo in Claude Code.
 */
import { createHash } from "node:crypto";
import {
  linkSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const EDIT_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"];
export const DEFAULT_TTL_MS = 5 * 60 * 1000;

/**
 * @typedef {{ holder: string, agent_type: string | null, path: string, acquired: number, touched: number }} Lease
 * @typedef {{ session_id?: string, agent_id?: string, agent_type?: string, cwd?: string,
 *             hook_event_name?: string, tool_name?: string,
 *             tool_input?: { file_path?: unknown, notebook_path?: unknown } }} HookInput
 */

/** @param {HookInput} input */
export function holderOf(input) {
  return `${input.session_id ?? "unknown"}:${input.agent_id ?? "main"}`;
}

/**
 * The file the tool is about to change, resolved so two agents naming it by
 * different routes (relative, through a symlinked directory) contend for one
 * lease. The file itself may not exist yet, so only its directory is resolved.
 * @param {HookInput} input
 * @returns {string | null}
 */
export function targetPath(input) {
  const raw = input.tool_input?.file_path ?? input.tool_input?.notebook_path;
  if (typeof raw !== "string" || raw === "") return null;
  const abs = isAbsolute(raw) ? raw : resolve(input.cwd ?? process.cwd(), raw);
  try {
    return join(realpathSync(dirname(abs)), basename(abs));
  } catch {
    return abs;
  }
}

/** @param {string} path */
export function leaseName(path) {
  return createHash("sha256").update(path).digest("hex").slice(0, 32) + ".json";
}

/**
 * @param {Lease | null} lease
 * @param {string} holder
 * @param {number} now
 * @param {number} ttlMs
 * @returns {boolean}
 */
export function mayTake(lease, holder, now, ttlMs) {
  if (lease === null) return true;
  if (lease.holder === holder) return true;
  if (now - lease.touched > ttlMs) return true;
  const session = holder.slice(0, holder.lastIndexOf(":"));
  return lease.holder === `${session}:main`;
}

/**
 * @param {string} file
 * @returns {Lease | null}
 */
export function readLease(file) {
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    return null;
  }
  try {
    /** @type {unknown} */
    const parsed = JSON.parse(text);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "holder" in parsed &&
      typeof parsed.holder === "string" &&
      "touched" in parsed &&
      typeof parsed.touched === "number"
    ) {
      return /** @type {Lease} */ (parsed);
    }
  } catch {
    /* unreadable lease: treated as absent, and replaced on the next take */
  }
  return null;
}

/**
 * Take or refresh the lease on `path`. Returns null when the caller now holds
 * it, or the lease that blocks it.
 * @param {{ dir: string, path: string, holder: string, agentType: string | null, now: number, ttlMs: number }} req
 * @returns {Lease | null}
 */
export function acquire(req, attempt = 0) {
  const { dir, path, holder, agentType, now, ttlMs } = req;
  mkdirSync(dir, { recursive: true });
  const file = join(dir, leaseName(path));
  const current = readLease(file);
  if (!mayTake(current, holder, now, ttlMs)) return current;

  /** @type {Lease} */
  const lease = {
    holder,
    agent_type: agentType,
    path,
    acquired: current !== null && current.holder === holder ? current.acquired : now,
    touched: now,
  };
  const tmp = `${file}.${process.pid}.${attempt}.tmp`;
  writeFileSync(tmp, JSON.stringify(lease));
  if (current !== null) {
    // Replacing a lease we may take. Two contenders taking over the same
    // expired lease can both win here; that needs a crashed holder and a
    // simultaneous pair, and the cost is the overlap this file already
    // tolerated before it existed.
    renameSync(tmp, file);
    return null;
  }
  try {
    // link() fails if the name exists, and the linked file already has its
    // content, so a reader can never see a half-written lease.
    linkSync(tmp, file);
    return null;
  } catch (err) {
    if (!(err instanceof Error) || !("code" in err) || err.code !== "EEXIST") throw err;
    // The name exists but read as absent. First time, assume we lost the race
    // for a free file and read the winner's lease. If it is still unreadable,
    // it is a corrupt lease, not a rival: replace it, or that file would stay
    // unprotected for good.
    if (attempt === 0) return acquire(req, 1);
    renameSync(tmp, file);
    return null;
  } finally {
    try {
      unlinkSync(tmp);
    } catch {
      /* already renamed away */
    }
  }
}

/**
 * Remove every lease `owned` selects, and any lease past its TTL.
 * @param {string} dir
 * @param {(lease: Lease) => boolean} owned
 * @param {number} now
 * @param {number} ttlMs
 * @returns {number} leases removed
 */
export function release(dir, owned, now, ttlMs) {
  let names;
  try {
    names = readdirSync(dir);
  } catch {
    return 0;
  }
  let removed = 0;
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    const file = join(dir, name);
    const lease = readLease(file);
    if (lease === null || !(owned(lease) || now - lease.touched > ttlMs)) continue;
    try {
      unlinkSync(file);
      removed++;
    } catch {
      /* another release got there first */
    }
  }
  return removed;
}

/**
 * @param {Lease} lease
 * @param {number} now
 * @param {number} ttlMs
 */
export function denyReason(lease, now, ttlMs) {
  const who = lease.agent_type ? `the ${lease.agent_type} agent` : "another agent";
  const secs = Math.max(0, Math.round((now - lease.touched) / 1000));
  const mins = Math.round(ttlMs / 60000);
  return (
    `${lease.path} is being edited by ${who} (last edit ${secs}s ago). ` +
    `Agents take turns on a file so their changes do not overwrite each other. ` +
    `Work on something else first, then retry this edit. The file frees when that agent ` +
    `finishes, or after ${mins} minute${mins === 1 ? "" : "s"} without an edit.`
  );
}

/**
 * The whole hook, minus stdin and stdout.
 * @param {string} raw hook input JSON
 * @param {{ dir: string, ttlMs: number, now: number }} opts
 * @returns {string} what to print on stdout ("" for nothing)
 */
export function handle(raw, opts) {
  const { dir, ttlMs, now } = opts;
  /** @type {unknown} */
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return "";
  }
  if (parsed === null || typeof parsed !== "object") return "";
  const input = /** @type {HookInput} */ (parsed);
  const holder = holderOf(input);
  const session = `${input.session_id ?? "unknown"}:`;

  switch (input.hook_event_name) {
    case "PreToolUse": {
      if (!EDIT_TOOLS.includes(input.tool_name ?? "")) return "";
      const path = targetPath(input);
      if (path === null) return "";
      const blocker = acquire({ dir, path, holder, agentType: input.agent_type ?? null, now, ttlMs });
      if (blocker === null) return "";
      return JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: denyReason(blocker, now, ttlMs),
        },
      });
    }
    case "SubagentStop":
      release(dir, (l) => l.holder === holder, now, ttlMs);
      return "";
    case "Stop":
      release(dir, (l) => l.holder === `${session}main`, now, ttlMs);
      return "";
    case "SessionEnd":
      release(dir, (l) => l.holder.startsWith(session), now, ttlMs);
      return "";
    default:
      return "";
  }
}

/** @param {NodeJS.ProcessEnv} env */
export function optionsFrom(env, now = Date.now()) {
  const ttl = Number(env.FILE_LEASE_TTL_MS);
  return {
    dir: env.FILE_LEASE_DIR || join(homedir(), ".claude", "file-leases"),
    ttlMs: Number.isFinite(ttl) && ttl > 0 ? ttl : DEFAULT_TTL_MS,
    now,
  };
}

/** @param {string | undefined} argv1 */
export function isEntrypoint(argv1) {
  if (!argv1) return false;
  try {
    return realpathSync(argv1) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

/**
 * Run as a hook: the decision for stdout and any warning for stderr. Never
 * throws, so the hook never exits non-zero.
 * @param {string} raw hook input
 * @param {NodeJS.ProcessEnv} env
 * @returns {{ stdout: string, stderr: string }}
 */
export function cli(raw, env) {
  try {
    return { stdout: handle(raw, optionsFrom(env)), stderr: "" };
  } catch (err) {
    return { stdout: "", stderr: `file-lease: allowing, lease state unavailable: ${String(err)}\n` };
  }
}

// Plain statements, no callbacks: this block runs only when Claude Code
// launches the file, so the spawned-node tests are what exercise it.
if (isEntrypoint(process.argv[1])) {
  let raw = "";
  try {
    raw = readFileSync(0, "utf8");
  } catch {
    /* no readable stdin: an empty input allows */
  }
  const result = cli(raw, process.env);
  process.stdout.write(result.stdout);
  process.stderr.write(result.stderr);
}
