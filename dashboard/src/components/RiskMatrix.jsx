import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ZAxis, ReferenceLine, Label } from 'recharts';
import { useMemo } from 'react';

const RiskMatrix = ({ issues }) => {
  const data = useMemo(() => {
    return issues.map(issue => {
      const impact = mapLevel(issue.impact);
      const urgency = mapLevel(issue.urgency);
      return {
        x: urgency,
        y: impact,
        z: impact * urgency, // Risk Score
        ...issue
      };
    });
  }, [issues]);

  const domain = [0, 6]; // 1-5 scale with padding

  return (
    <div className="h-[400px] w-full bg-slate-900/50 rounded-lg p-4 relative">
       {/* Quadrant Backgrounds */}
       <div className="absolute inset-0 grid grid-cols-2 grid-rows-2 opacity-10 pointer-events-none">
          <div className="bg-green-500 rounded-tl-lg"></div> {/* Low/High -> Medium? No, Low Urgency, High Impact? */}
          <div className="bg-orange-500 rounded-tr-lg"></div> {/* High Urgency, High Impact -> Critical */}
          <div className="bg-blue-500 rounded-bl-lg"></div> {/* Low Urgency, Low Impact -> Low */}
          <div className="bg-yellow-500 rounded-br-lg"></div> {/* High Urgency, Low Impact -> Medium */}
       </div>

      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis 
            type="number" 
            dataKey="x" 
            name="Urgency" 
            domain={domain} 
            stroke="#94a3b8" 
            tickCount={6}
            label={{ value: 'Urgency (Time Criticality)', position: 'bottom', fill: '#94a3b8' }}
          />
          <YAxis 
            type="number" 
            dataKey="y" 
            name="Impact" 
            domain={domain} 
            stroke="#94a3b8" 
            tickCount={6}
            label={{ value: 'Impact (Project Severity)', angle: -90, position: 'insideLeft', fill: '#94a3b8' }}
          />
          <ZAxis type="number" dataKey="z" range={[50, 400]} name="Risk Score" />
          
          <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3' }} />
          
          <ReferenceLine y={3} stroke="#ef4444" strokeDasharray="3 3" />
          <ReferenceLine x={3} stroke="#ef4444" strokeDasharray="3 3" />

          <Scatter name="Issues" data={data} fill="#8884d8">
            {data.map((entry, index) => (
              <cell key={`cell-${index}`} fill={getColor(entry.z)} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
};

// Helpers
const mapLevel = (val) => {
  if (!val) return 1;
  const v = val.toLowerCase();
  if (['critical', 'immediate', 'very high'].includes(v)) return 5;
  if (['high'].includes(v)) return 4;
  if (['medium', 'moderate'].includes(v)) return 3;
  if (['low'].includes(v)) return 2;
  return 1; // negligible/planned
};

const getColor = (score) => {
  if (score >= 20) return '#ef4444'; // Critical (Red)
  if (score >= 12) return '#f97316'; // High (Orange)
  if (score >= 6) return '#eab308';  // Medium (Yellow)
  return '#3b82f6';                  // Low (Blue)
};

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="bg-slate-800 border border-slate-700 p-3 rounded shadow-xl text-slate-100 z-50">
        <p className="font-bold text-sm mb-1">{data.issue_id}</p>
        <p className="text-xs text-slate-300">{data.title}</p>
        <div className="mt-2 flex gap-2 text-xs">
           <span className="text-slate-400">Impact: {data.impact}</span>
           <span className="text-slate-400">Urgency: {data.urgency}</span>
        </div>
        <p className="mt-1 text-xs font-mono text-emerald-400">Score: {data.z}</p>
      </div>
    );
  }
  return null;
};

export default RiskMatrix;
