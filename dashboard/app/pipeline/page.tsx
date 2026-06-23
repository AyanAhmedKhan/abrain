import { getPipeline, getOwnerSuggestions } from "@/lib/data";
import { PageHeader } from "@/components/ui";
import Board from "@/components/Board";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [deals, owners] = await Promise.all([getPipeline(), getOwnerSuggestions()]);
  return (
    <div className="space-y-5">
      <PageHeader title="Pipeline" count={deals.length} subtitle="Drag between stages · click the owner to assign" />
      {deals.length === 0
        ? <div className="card p-8 text-center text-dim">No deals in the pipeline yet.</div>
        : <Board deals={deals} owners={owners} />}
    </div>
  );
}
