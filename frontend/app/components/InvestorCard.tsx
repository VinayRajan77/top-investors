import Link from 'next/link';
import { Investor } from './types';

const compact=(n:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:1}).format(n);
const palette=['bg-[#e5f3eb] text-[#155d3a]','bg-[#e9edff] text-[#303f9f]','bg-[#fff0dd] text-[#9a4d00]','bg-[#fce8ee] text-[#a42551]','bg-[#e4f4f7] text-[#11647a]'];
const initials=(value:string)=>value.split(/\s+/).filter(Boolean).slice(0,2).map(part=>part[0]).join('').toUpperCase();
const date=(value:string|null)=>value?new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric'}).format(new Date(`${value}T00:00:00`)):'Awaiting import';

export default function InvestorCard({investor}:{investor:Investor}) {
  const positive=(investor.performance??0)>=0;
  const cardTone=palette[investor.name.length%palette.length];
  return <Link href={`/investors/${investor.slug}`} className="group relative block overflow-hidden rounded-3xl border border-[#dce4db] bg-paper p-5 shadow-card transition duration-200 hover:-translate-y-1 hover:border-[#9ac9b2] hover:shadow-xl">
    <div className="absolute right-0 top-0 h-24 w-24 rounded-bl-[5rem] bg-[#f1f7ef] transition group-hover:bg-[#e3f1e4]"/>
    <div className="relative flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl text-sm font-black shadow-sm ${cardTone}`}>{initials(investor.name)}</span>
        <div className="min-w-0"><h2 className="truncate text-lg font-bold leading-tight group-hover:text-moss">{investor.name}</h2><p className="mt-1 truncate text-sm text-slate-500">{investor.fund_name}</p></div>
      </div>
      {investor.performance !== null && <span title="Approximate change in disclosed portfolio value over one year; not a fund return." className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-bold ${positive?'bg-emerald-50 text-emerald-700':'bg-rose-50 text-rose-700'}`}>{positive?'+':''}{investor.performance.toFixed(1)}%</span>}
    </div>
    <div className="relative mt-6 flex items-end justify-between gap-3">
      <div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">Reported portfolio</p><p className="mt-1 text-2xl font-black tracking-tight">{investor.total_value ? compact(investor.total_value) : 'Awaiting import'}</p></div>
      <span className="rounded-full bg-[#f4f7f3] px-2.5 py-1 text-xs font-semibold text-slate-600">{investor.holding_count || '—'} positions</span>
    </div>
    <div className="relative mt-5 space-y-2 border-t border-[#edf0ea] pt-4">
      {investor.holdings.length ? investor.holdings.map((holding,index)=><div key={`${holding.ticker||holding.company_name}-${index}`} className="flex items-center gap-2 text-sm"><span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[9px] font-black ${palette[index%palette.length]}`}>{holding.ticker||initials(holding.company_name)}</span><span className="min-w-0 flex-1 truncate font-medium">{holding.company_name}</span>{holding.ticker&&<span className="text-xs font-bold text-slate-400">{holding.ticker}</span>}</div>) : <p className="text-sm leading-5 text-slate-400">No usable 13F holdings have been imported for this manager yet.</p>}
    </div>
    <div className="relative mt-4 flex items-center justify-between text-xs"><span className="text-slate-400">Latest filing · {date(investor.filing_date)}</span>{investor.holding_count>3&&<span className="font-bold text-moss">Explore portfolio →</span>}</div>
  </Link>
}
