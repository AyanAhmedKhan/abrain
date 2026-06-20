import { getDeals } from "@/lib/data";
import CompaniesTable from "@/components/CompaniesTable";

export const dynamic = "force-dynamic";

export default async function Page() {
  const deals = await getDeals();
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold">Deals <span className="text-dim font-normal">({deals.length})</span></h1>
      <CompaniesTable companies={deals} />
    </div>
  );
}
