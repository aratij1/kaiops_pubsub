import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.csrf.DefaultCrumbIssuer
import jenkins.model.Jenkins
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def jenkins = Jenkins.get()
def username = System.getenv('JENKINS_BOOTSTRAP_USERNAME') ?: 'kaiops'
def password = System.getenv('JENKINS_BOOTSTRAP_PASSWORD') ?: 'kaiops-local-token'

def realm = new HudsonPrivateSecurityRealm(false)
realm.createAccount(username, password)
jenkins.setSecurityRealm(realm)
jenkins.setAuthorizationStrategy(new hudson.security.FullControlOnceLoggedInAuthorizationStrategy())
jenkins.setCrumbIssuer(new DefaultCrumbIssuer(true))

def jobName = 'kaiops-auto-remediation'
def pipelineSource = new File('/opt/kaiops/Jenkinsfile.auto-remediation').text
def job = jenkins.getItem(jobName) as WorkflowJob
if (job == null) {
    job = jenkins.createProject(WorkflowJob, jobName)
}
job.setDefinition(new CpsFlowDefinition(pipelineSource, true))
job.setDescription('Governed KaiMS application resolution pipeline. Dry-run is enabled by default.')
job.save()
jenkins.save()
