"""Scientific plot of all paired CPU ratios and predeclared summaries."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=Path(__file__).resolve().parent
read=lambda n:json.loads((p/n).read_text())
items=[('A/A · même code',read('paired-cast-final-cpu2-aa-summary.json')['conditions'][0],'#717b88')]
for s in read('paired-cast-final-cpu2-summary.json')['conditions']:
    items.append((f'{s["case"]} · lot {s["batch_size"]}',s,'#2868b2'))
items.extend([
    ('50k · processus persistants',read('paired-cast-confirmation-cpu2-summary.json')['conditions'][0],'#a35410'),
    ('50k · processus neufs',read('paired-cast-confirmation-fresh-cpu2-summary.json')['conditions'][0],'#a35410'),
])
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'svg.hashsalt':'graflo-casting-20261029'})
fig,ax=plt.subplots(figsize=(11,6.2))
for y,(_,s,color) in enumerate(items):
    vals=s['cpu_ratios'];center=s['median_cpu_speedup'];lo,hi=s['cpu_speedup_ci95']
    ax.scatter(vals,[y+(i-(len(vals)-1)/2)*.025 for i in range(len(vals))],s=17,c=color,alpha=.4,zorder=2)
    ax.plot([lo,hi],[y,y],c=color,lw=3,zorder=3)
    ax.scatter([center],[y],c=color,s=45,marker='D',zorder=4)
ax.axvline(1,c='#343d4a',lw=1)
ax.axvline(1/.97,c='#555',ls='--',lw=.9,label='Seuil de baisse CPU 3 %')
ax.set_yticks(range(len(items)),[name for name,_,_ in items]);ax.invert_yaxis()
ax.set_xlabel('Accélération CPU = temps référence / temps candidat  →  plus rapide')
ax.set_title('GraFlo · toutes les paires conservées, même CPU logique\nPoints : paires · losange : médiane · barre : IC95 bootstrap',loc='left',pad=15)
ax.grid(axis='x',alpha=.2);ax.legend(loc='lower right',fontsize=9)
ax.spines[['top','right','left']].set_visible(False)
fig.tight_layout()
fig.savefig(p/'casting-comparison.svg',metadata={'Date':None})
fig.savefig(p/'casting-comparison.png',dpi=160)
