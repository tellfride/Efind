import { Construction } from "lucide-react";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";

/** Página provisória — substituída pela implementação do módulo */
export function ModulePlaceholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card>
        <EmptyState icon={Construction} title="Em construção" description="Este módulo está sendo implementado." />
      </Card>
    </>
  );
}
