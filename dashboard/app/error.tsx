"use client";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="card p-10 text-center space-y-3">
      <h2 className="text-lg font-semibold">Data temporarily unavailable</h2>
      <p className="text-dim text-sm">
        The brain’s database didn’t respond. This is usually transient — try again.
      </p>
      <button onClick={() => reset()}
        className="px-4 py-2 rounded-lg bg-accent text-white font-medium transition-colors hover:bg-accentd">
        Retry
      </button>
    </div>
  );
}
