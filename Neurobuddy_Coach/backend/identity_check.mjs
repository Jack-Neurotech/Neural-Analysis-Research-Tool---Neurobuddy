import { createInterface } from 'node:readline';
import { getIdentity } from '../cursor/identity.js';

const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
  if (!line.trim()) continue;
  let headers = {};
  try {
    headers = JSON.parse(line);
  } catch {
    headers = {};
  }
  const identity = await getIdentity(headers);
  const safe = identity.verified
    ? {
        verified: true,
        sub: identity.sub,
        kind: identity.kind,
        stage: identity.stage || 'production',
      }
    : { verified: false, reason: identity.reason || 'missing_header' };
  process.stdout.write(JSON.stringify(safe) + '\n');
}
