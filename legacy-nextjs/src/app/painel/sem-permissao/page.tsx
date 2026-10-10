import { ShieldOff } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/misc";

export const metadata = { title: "Sem permissão" };

export default function SemPermissaoPage() {
  return (
    <Card>
      <EmptyState
        icon={ShieldOff}
        title="Você não tem acesso a esta área"
        description="As permissões de cada módulo são definidas pelo administrador da campanha. Se precisar de acesso, fale com ele."
        action={<ButtonLink href="/painel/meu-link" variant="outline">Ir para meu link de cadastro</ButtonLink>}
      />
    </Card>
  );
}
