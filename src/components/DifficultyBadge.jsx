const colors={Beginner:'bg-emerald-100 text-emerald-700',Intermediate:'bg-amber-100 text-amber-700',Advanced:'bg-rose-100 text-rose-700'}
export default function DifficultyBadge({level}) { return <span className={`rounded-full px-2.5 py-1 text-xs font-extrabold ${colors[level]||colors.Beginner}`}>{level?.toUpperCase()}</span> }
