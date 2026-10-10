import { SearchX } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/misc";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <EmptyState
        icon={SearchX}
        title="Página não encontrada"
        description="O endereço acessado não existe ou você não tem acesso a ele."
        action={<ButtonLink href="/">Voltar ao início</ButtonLink>}
      />
    </div>
  );
}
