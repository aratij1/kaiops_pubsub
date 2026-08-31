import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.csrf.DefaultCrumbIssuer
import hudson.model.BooleanParameterDefinition
import hudson.model.ParametersDefinitionProperty
import hudson.model.StringParameterDefinition
import hudson.model.TextParameterDefinition
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
// Declarative Pipeline parameters are normally materialized only after the
// first build. KaiOps calls buildWithParameters for that first build, so seed
// the same contract during bootstrap and keep it refreshed on every restart.
job.removeProperty(ParametersDefinitionProperty)
job.addProperty(new ParametersDefinitionProperty([
    new StringParameterDefinition('KAI_OPS_INCIDENT_ID', '', 'KaiOps incident UUID'),
    new StringParameterDefinition('KAI_OPS_APPROVAL_ID', '', 'Recorded approval identifier'),
    new StringParameterDefinition('KAI_OPS_APPLICATION_ID', '', 'Registered application identifier'),
    new StringParameterDefinition('KAI_OPS_TARGET', '', 'Governed remediation target'),
    new StringParameterDefinition('KAI_OPS_SERVICE', '', 'Affected service'),
    new StringParameterDefinition('KAI_OPS_ENVIRONMENT', 'prod', 'Target environment'),
    new StringParameterDefinition('KAI_OPS_NAMESPACE', 'default', 'Target namespace'),
    new StringParameterDefinition('KAI_OPS_RESOLUTION_ID', 'investigate-first', 'Approved resolution'),
    new BooleanParameterDefinition('KAI_OPS_DRY_RUN', true, 'Validate without applying changes'),
    new TextParameterDefinition('KAI_OPS_EXECUTION_PLAN', '{"commands":[],"scripts":[],"queries":[]}', 'Approved execution plan'),
    new StringParameterDefinition('KAI_OPS_PLAN_DIGEST', '', 'SHA-256 digest of the exact approved execution plan'),
]))
job.save()
jenkins.save()
