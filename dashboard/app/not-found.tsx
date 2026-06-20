import Link from "next/link";

export default function NotFound() {
  return (
    <div className="card p-10 text-center space-y-2">
      <h2 className="text-lg font-semibold">Not found</h2>
      <p className="text-dim text-sm">That page or company doesn’t exist.</p>
      <Link href="/" className="text-accent hover:underline">← Dashboard</Link>
    </div>
  );
}
