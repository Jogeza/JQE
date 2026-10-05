import { ArrowRight, Check, ShieldCheck } from 'lucide-react';

export type UpgradePlan = { key: string; name: string; price: number | null; currency: string | null; status: string };
const details: Record<string, {period:string;description:string}> = {
  trial:{period:'24 hours',description:'A focused introduction to your JQE workspace.'},
  subscription:{period:'per month',description:'A continuing workspace for disciplined market research.'},
  lifetime:{period:'one-time',description:'Long-term access without a monthly subscription.'},
};
export function UpgradePlans({plans,onBack}: {plans:UpgradePlan[];onBack:()=>void}) {
  const visible = ['trial','subscription','lifetime'].flatMap(key => plans.filter(plan => plan.key === key));
  return <main className="auth-page auth-upgrade-page"><section className="auth-panel auth-upgrade-panel">
    <button className="auth-back" onClick={onBack}>Back to workspace <ArrowRight size={15}/></button>
    <p className="auth-eyebrow">JQE PREMIUM ACCESS</p><h1>A workspace for your next decision.</h1>
    <p className="upgrade-intro">Choose your access period. Market evidence, research and a clear view of risk belong in one place.</p>
    <div className="upgrade-plan-grid">{visible.map(plan => <article key={plan.key} className={`upgrade-plan ${plan.key==='subscription'?'upgrade-plan-featured':''}`}>
      <span className="upgrade-plan-label">{plan.key==='subscription'?'ONGOING ACCESS':plan.key==='lifetime'?'LONG-TERM ACCESS':'EXPLORE JQE'}</span>
      <h2>{plan.name}</h2><p>{details[plan.key].description}</p>
      <div className="upgrade-price">{plan.price != null && plan.currency==='USD' ? <><strong>${plan.price.toLocaleString('en-US')}</strong><span>USD · {details[plan.key].period}</span></> : <strong>Price unavailable</strong>}</div>
      <ul><li><Check size={15}/> Market charts and workspace</li><li><Check size={15}/> Research and decision evidence</li><li><Check size={15}/> AI analysis within plan quotas</li></ul>
      <button disabled className="auth-primary">Checkout coming soon</button>
    </article>)}</div>
    {!visible.length && <p role="status">The plan catalog is unavailable. Please refresh later.</p>}
    <div className="upgrade-assurance"><ShieldCheck size={22}/><div><strong>Evidence first. Risk always controlled.</strong><p>Plans grant software access, not guaranteed returns or permission to bypass trading safeguards. Provider and AI quotas apply. Payments are not collected until checkout is configured.</p></div></div>
  </section></main>;
}
