// Tipos trocados entre as páginas (servidor) e os componentes cliente do módulo Equipe/Permissões.
// Apenas dados serializáveis e sem segredos (nunca hash de senha).
import type { CampaignRole, ConfigurableRole } from "@/lib/constants";
import type { OverrideMatrix } from "./permission-logic";

/** Membro da equipe já com contagens de eleitores (lista e hierarquia) */
export interface TeamMemberDTO {
  id: string;
  name: string;
  email: string;
  /** Telefone formatado para exibição ("(11) 98765-4321") ou null */
  phone: string | null;
  role: CampaignRole;
  parentId: string | null;
  parentName: string | null;
  parentRole: CampaignRole | null;
  active: boolean;
  goal: number | null;
  region: string | null;
  votersTotal: number;
  voters7d: number;
  /** Último acesso já formatado no servidor (evita divergência de hidratação) */
  lastLoginLabel: string;
  isSelf: boolean;
}

/** Opção de membro para selects (superior, transferência de eleitores...) */
export interface MemberOption {
  id: string;
  name: string;
  role: CampaignRole;
  active: boolean;
}

/** Dados exibidos uma única vez após criar um membro */
export interface CreatedMemberData {
  id: string;
  name: string;
  email: string;
  password: string;
  loginUrl: string;
  registrationUrl: string;
  /** Mensagem pronta com os dados de acesso */
  message: string;
  /** wa.me com a mensagem (null quando o membro não tem telefone) */
  whatsappUrl: string | null;
}

/** Dados exibidos uma única vez após redefinir a senha */
export interface ResetPasswordData {
  email: string;
  password: string;
  loginUrl: string;
  message: string;
  whatsappUrl: string | null;
}

/** Membro editável no modal de edição */
export interface EditableMember {
  id: string;
  name: string;
  email: string;
  /** Telefone formatado para o input */
  phone: string;
  role: CampaignRole;
  parentId: string | null;
  goal: number | null;
  region: string | null;
  active: boolean;
  isSelf: boolean;
  votersTotal: number;
  childrenCount: number;
}

/** Usuário (coordenador/cabo) na tela de exceções de permissão */
export interface OverrideUserDTO {
  id: string;
  name: string;
  role: ConfigurableRole;
  active: boolean;
  overrides: OverrideMatrix;
}
