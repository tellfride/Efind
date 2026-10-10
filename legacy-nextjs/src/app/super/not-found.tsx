import { SearchX } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/misc";

export default function SuperNotFound() {
  return (
    <Card>
      <EmptyState
        icon={SearchX}
        title="Não encontrado"
        description="A campanha ou página acessada não existe ou foi excluída."
        action={<ButtonLink href="/super/campanhas">Ver campanhas</ButtonLink>}
      />
    </Card>
  );
}
