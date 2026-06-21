import { getDeals } from "@/lib/data";
import CompaniesTable from "@/components/CompaniesTable";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Page() {
  const deals = await getDeals();
  return (
    <div className="space-y-6">
      <PageHeader title="Deals" count={deals.length} subtitle="Companies actively in the deal pipeline." />
      <CompaniesTable companies={deals} />
    </div>
  );
}
