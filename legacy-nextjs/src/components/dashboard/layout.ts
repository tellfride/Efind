// Grade dos dashboards: 1 coluna no celular, 2 no tablet e 4 no desktop.
// As classes ficam escritas por extenso para o Tailwind encontrá-las.
import type { WidgetSize } from "@/lib/dashboard-types";

export const DASHBOARD_GRID_CLASS = "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4";

export const WIDGET_SIZE_CLASS: Record<WidgetSize, string> = {
  sm: "col-span-1",
  md: "col-span-1 md:col-span-2",
  lg: "col-span-1 md:col-span-2 xl:col-span-3",
  full: "col-span-1 md:col-span-2 xl:col-span-4",
};
