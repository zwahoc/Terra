import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { supplyViews, terra } from '../data/terra';
import { positiveQuantity } from '../lib/quantities';

/** Original Inventory graphics, using counts of loaded supply records, never mixed-unit sums. */
export default function SupplyGraphics({supplies}:{supplies:typeof supplyViews}){
 const animate=typeof matchMedia==='undefined'||!matchMedia('(prefers-reduced-motion: reduce)').matches;
 const ready=supplies.filter(s=>positiveQuantity(s.reservable_quantity)).length;
 const held=supplies.filter(s=>positiveQuantity(s.reserved_active_quantity)).length;
 const review=supplies.filter(s=>s.surplus_status!=='CONFIRMED').length;
 const status=[{name:'Available',value:ready,fill:'#629565'},{name:'Reserved',value:held,fill:'#c4a456'},{name:'Review',value:review,fill:'#698a9b'}];
 const categories=[...new Set(supplies.map(s=>terra.materials.find(m=>m.id===s.material_id)?.category||'Other'))].sort();
 const mix=categories.map(name=>({name:name.toLowerCase().replaceAll('_',' '),value:supplies.filter(s=>(terra.materials.find(m=>m.id===s.material_id)?.category||'Other')===name).length}));
 const colors=['#629565','#c4a456','#698a9b','#99798a','#7d9875'];
 return <section className="restored-supply-graphics" aria-label="Supply overview">
 <div className="restored-supply-summary">{[{label:'Material lines',value:supplies.length},{label:'Available to reserve',value:ready},{label:'Currently reserved',value:held},{label:'Needs review',value:review}].map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}</div>
 <div className="restored-chart-grid"><section className="restored-status-chart"><header><h2>Supply status</h2><span>Supply records</span></header><div role="img" aria-label={`Supply status: ${ready} available, ${held} reserved, ${review} need review`}><ResponsiveContainer width="100%" height={170}><BarChart data={status} margin={{top:8,right:20,left:-20,bottom:0}}><XAxis dataKey="name" tickLine={false} axisLine={false} tick={{fill:'#355f50',fontSize:12}}/><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{fill:'#355f50',fontSize:12}}/><Tooltip cursor={{fill:'#cadfc7'}}/><Bar dataKey="value" name="Supply records" radius={[5,5,0,0]} isAnimationActive={animate} animationDuration={550}>{status.map(s=><Cell key={s.name} fill={s.fill}/>)}</Bar></BarChart></ResponsiveContainer></div></section>
 <section className="restored-mix-chart"><header><h2>Material categories</h2><span>Supply records</span></header>{mix.length?<div className="restored-donut"><div role="img" aria-label={mix.map(m=>`${m.name}: ${m.value} supply records`).join(', ')}><ResponsiveContainer width="100%" height={170}><PieChart><Pie data={mix} dataKey="value" nameKey="name" innerRadius={46} outerRadius={70} paddingAngle={3} isAnimationActive={animate} animationDuration={550}>{mix.map((m,i)=><Cell key={m.name} fill={colors[i%colors.length]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer></div><ul>{mix.map((m,i)=><li key={m.name}><span className="restored-chart-key" style={{background:colors[i%colors.length]}} aria-hidden="true"/><span>{m.name}</span><b>{m.value}</b></li>)}</ul></div>:<p className="restored-chart-empty">No released supply yet.</p>}</section></div>
 </section>;
}
