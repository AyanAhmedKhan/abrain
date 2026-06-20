import { Pool } from "pg";

// One pooled connection, reused across hot-reloads / server components.
const g = global as unknown as { _pgPool?: Pool };
export const pool =
  g._pgPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false }, // Supabase
    max: 5,
    idleTimeoutMillis: 30_000,
  });
if (!g._pgPool) g._pgPool = pool;

export async function q<T = any>(sql: string, params: any[] = []): Promise<T[]> {
  const r = await pool.query(sql, params);
  return r.rows as T[];
}
