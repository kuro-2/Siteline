import { TopBar } from "@/components/TopBar";
import { SurveyFlow } from "./SurveyFlow";

export default async function SurveyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <>
      <TopBar />
      <main id="main" className="mx-auto max-w-xl px-4 py-8">
        <SurveyFlow slug={slug} />
      </main>
    </>
  );
}
