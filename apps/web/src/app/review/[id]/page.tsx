import { StaffGate } from "@/components/StaffGate";
import { TopBar } from "@/components/TopBar";
import { ReviewScreen } from "./ReviewScreen";

export default async function ReviewDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <TopBar />
      <StaffGate>
        <ReviewScreen id={id} />
      </StaffGate>
    </>
  );
}
