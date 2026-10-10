// Ícones do catálogo de widgets (nomes em src/lib/dashboard-types.ts → componentes lucide-react)
import {
  Building2,
  Cake,
  CalendarCheck,
  ChartArea,
  ChartPie,
  Clock,
  Flag,
  HeartHandshake,
  MapPin,
  Megaphone,
  MessageCircle,
  Network,
  QrCode,
  Send,
  Target,
  TrendingUp,
  Trophy,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { WIDGET_CATALOG, type WidgetIconName, type WidgetType } from "@/lib/dashboard-types";

export const WIDGET_ICONS: Record<WidgetIconName, LucideIcon> = {
  UsersRound,
  CalendarCheck,
  TrendingUp,
  Target,
  MessageCircle,
  Users,
  Trophy,
  Network,
  ChartArea,
  MapPin,
  Building2,
  ChartPie,
  HeartHandshake,
  QrCode,
  Cake,
  Clock,
  Send,
  Flag,
  Megaphone,
};

export function widgetIcon(type: WidgetType): LucideIcon {
  return WIDGET_ICONS[WIDGET_CATALOG[type].icon];
}
