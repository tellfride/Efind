import {
  BarChart3,
  FileText,
  History,
  KeyRound,
  LayoutDashboard,
  Map,
  MessageSquareText,
  PlugZap,
  QrCode,
  Send,
  Settings,
  ShieldCheck,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import type { ModuleKey } from "@/lib/permissions";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Módulo exigido (permissão "view"). */
  module?: ModuleKey;
  /** Apenas ADMIN (ex.: matriz de permissões) */
  adminOnly?: boolean;
  /** Marca ativo apenas quando o caminho é exatamente igual */
  exact?: boolean;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const PANEL_NAV: NavSection[] = [
  {
    title: "Visão geral",
    items: [
      { href: "/painel", label: "Início", icon: LayoutDashboard, module: "dashboard", exact: true },
      { href: "/painel/dashboards", label: "Dashboards", icon: BarChart3, module: "dashboard" },
    ],
  },
  {
    title: "Eleitores",
    items: [
      { href: "/painel/eleitores", label: "Eleitores", icon: UsersRound, module: "eleitores" },
      { href: "/painel/mapa", label: "Mapa", icon: Map, module: "mapa" },
      { href: "/painel/meu-link", label: "Meu link / QR Code", icon: QrCode, module: "meu_link" },
    ],
  },
  {
    title: "Equipe",
    items: [
      { href: "/painel/equipe", label: "Equipe", icon: Users, module: "equipe" },
      { href: "/painel/permissoes", label: "Permissões", icon: KeyRound, adminOnly: true },
    ],
  },
  {
    title: "WhatsApp",
    items: [
      { href: "/painel/mensagens/modelos", label: "Modelos de mensagem", icon: MessageSquareText, module: "modelos" },
      { href: "/painel/mensagens/disparos", label: "Disparos", icon: Send, module: "disparos" },
      { href: "/painel/whatsapp", label: "Conexão da API", icon: PlugZap, module: "whatsapp" },
    ],
  },
  {
    title: "Campanha",
    items: [
      { href: "/painel/configuracoes", label: "Configurações", icon: Settings, module: "configuracoes" },
      { href: "/painel/auditoria", label: "Auditoria", icon: History, module: "auditoria" },
    ],
  },
];

export const SUPER_NAV: NavSection[] = [
  {
    title: "Plataforma",
    items: [
      { href: "/super", label: "Visão geral", icon: LayoutDashboard, exact: true },
      { href: "/super/campanhas", label: "Candidatos / campanhas", icon: ShieldCheck },
      { href: "/super/usuarios", label: "Super admins", icon: Users },
      { href: "/super/auditoria", label: "Auditoria", icon: History },
    ],
  },
  {
    title: "Conta",
    items: [{ href: "/super/perfil", label: "Meu perfil", icon: FileText }],
  },
];
