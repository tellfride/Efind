import { ProgressBar } from "@/components/ui/misc";
import { cn, formatNumber, formatPercent } from "@/lib/utils";
import { goalPercent, goalTone } from "./team-logic";

/** Barra de progresso da meta de cadastros (ou "Sem meta") */
export function GoalMeter({
  total,
  goal,
  className,
  barClassName = "w-20 sm:w-24",
  showGoal = true,
}: {
  total: number;
  goal: number | null;
  className?: string;
  barClassName?: string;
  showGoal?: boolean;
}) {
  const pct = goalPercent(total, goal);
  if (pct === null) return <span className={cn("text-xs text-slate-400", className)}>Sem meta</span>;
  return (
    <span className={cn("inline-flex items-center gap-2", className)} title={`${formatNumber(total)} de ${formatNumber(goal)} cadastros`}>
      <ProgressBar value={pct} max={100} tone={goalTone(pct)} className={barClassName} />
      <span className="text-xs whitespace-nowrap text-slate-600 tabular-nums">
        {formatPercent(pct, 0)}
        {showGoal && <span className="text-slate-400"> de {formatNumber(goal)}</span>}
      </span>
    </span>
  );
}
