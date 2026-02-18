import { useState, useEffect } from 'react'
import { Activity, AlertTriangle, CheckCircle, Clock } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card"
import RiskMatrix from "./components/RiskMatrix"

function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/data.json')
      .then(res => res.json())
      .then(jsonData => {
        setData(jsonData)
        setLoading(false)
      })
      .catch(err => console.error("Failed to load data:", err))
  }, [])

  if (loading) {
    return <div className="min-h-screen bg-background flex items-center justify-center text-white">Loading P5 Dashboard...</div>
  }

  const { stats, issues, meetings } = data

  return (
    <div className="min-h-screen bg-background p-8 font-sans text-foreground">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">P5 Project Command Center</h1>
          <p className="text-muted-foreground">Real-time Intelligence Dashboard</p>
        </div>
        <div className="text-sm text-muted-foreground">
          Last Updated: {new Date(data.generated_at).toLocaleString()}
        </div>
      </header>

      {/* Stats Overview */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8">
        <StatsCard title="Total Issues" value={stats.total_issues} icon={Activity} />
        <StatsCard title="Critical Risks" value={stats.critical_issues} icon={AlertTriangle} className="text-destructive" />
        <StatsCard title="Open Issues" value={stats.open_issues} icon={Clock} />
        <StatsCard title="Recent Meetings" value={stats.recent_meetings} icon={CheckCircle} />
      </div>

      <div className="grid gap-8 md:grid-cols-7 lg:grid-cols-7">
        {/* Risk Matrix (Main) */}
        <Card className="col-span-4 bg-card border-border">
          <CardHeader>
            <CardTitle>Risk Matrix (Impact vs Urgency)</CardTitle>
          </CardHeader>
          <CardContent>
            <RiskMatrix issues={issues} />
          </CardContent>
        </Card>

        {/* Recent Meetings (Side) */}
        <Card className="col-span-3 bg-card border-border">
          <CardHeader>
            <CardTitle>Recent Intelligence</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {meetings.slice(0, 5).map((meeting, i) => (
                <div key={i} className="flex flex-col space-y-1 border-b border-border pb-2 last:border-0">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-sm text-primary">{meeting.title}</span>
                    <span className="text-xs text-muted-foreground">{meeting.date}</span>
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {meeting.summary || "Analysis completed."}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Issues Table (Bottom) */}
       <div className="mt-8">
        <h2 className="text-2xl font-bold mb-4">Active Issues</h2>
        <div className="overflow-x-auto rounded-md border border-border">
           <table className="w-full text-sm text-left">
             <thead className="bg-muted text-muted-foreground uppercase">
               <tr>
                 <th className="px-4 py-3">ID</th>
                 <th className="px-4 py-3">Title</th>
                 <th className="px-4 py-3">Priority</th>
                 <th className="px-4 py-3">Status</th>
                 <th className="px-4 py-3">Owner</th>
                 <th className="px-4 py-3">Due Date</th>
               </tr>
             </thead>
             <tbody>
               {issues.map((issue) => (
                 <tr key={issue.issue_id} className="border-b border-border hover:bg-muted/50">
                   <td className="px-4 py-3 font-medium">{issue.issue_id}</td>
                   <td className="px-4 py-3">{issue.title}</td>
                   <td className="px-4 py-3">
                     <span className={cn(
                       "inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ring-1 ring-inset",
                       issue.priority?.toLowerCase() === 'critical' ? 'bg-red-400/10 text-red-400 ring-red-400/20' : 
                       issue.priority?.toLowerCase() === 'high' ? 'bg-orange-400/10 text-orange-400 ring-orange-400/20' :
                       'bg-blue-400/10 text-blue-400 ring-blue-400/20'
                     )}>
                       {issue.priority}
                     </span>
                   </td>
                   <td className="px-4 py-3">{issue.status}</td>
                   <td className="px-4 py-3">{issue.assignee || "-"}</td>
                   <td className="px-4 py-3">{issue.due_date || "-"}</td>
                 </tr>
               ))}
             </tbody>
           </table>
        </div>
      </div>

    </div>
  )
}

function StatsCard({ title, value, icon: Icon, className }) {
  return (
    <Card className="bg-card border-border">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">
          {title}
        </CardTitle>
        <Icon className={cn("h-4 w-4 text-muted-foreground", className)} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
      </CardContent>
    </Card>
  )
}

export default App
