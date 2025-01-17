import requests
import time
from os import makedirs
import urllib.parse
from nordstream.utils.errors import GitHubError, GitHubBadCredentials
from nordstream.utils.log import logger
from nordstream.git import Git
from nordstream.utils.constants import *


class GitHub:
    _DEFAULT_BRANCH_NAME = DEFAULT_BRANCH_NAME
    _token = None
    _auth = None
    _org = None
    _githubLogin = None
    _repos = []
    _header = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    _repoURL = "https://api.github.com/repos"
    _session = None
    _branchName = _DEFAULT_BRANCH_NAME
    _outputDir = OUTPUT_DIR
    _sleepTime = 15
    _maxRetry = 10
    _isGHSToken = False

    def __init__(self, token):
        self._token = token
        self._auth = ("foo", self._token)
        self._session = requests.Session()
        if token.lower().startswith("ghs_"):
            self._isGHSToken = True

        self._githubLogin = self.__getLogin()

    @staticmethod
    def checkToken(token):
        logger.verbose(f"Checking token: {token}")

        headers = GitHub._header
        headers["Authorization"] = f"token {token}"

        data = {"query": "query UserCurrent{viewer{login}}"}

        return requests.post("https://api.github.com/graphql", headers=headers, json=data).status_code == 200

    @property
    def token(self):
        return self._token

    @property
    def org(self):
        return self._org

    @org.setter
    def org(self, org):
        self._org = org

    @property
    def defaultBranchName(self):
        return self._DEFAULT_BRANCH_NAME

    @property
    def branchName(self):
        return self._branchName

    @branchName.setter
    def branchName(self, value):
        self._branchName = value

    @property
    def repos(self):
        return self._repos

    @property
    def outputDir(self):
        return self._outputDir

    @outputDir.setter
    def outputDir(self, value):
        self._outputDir = value

    def __getLogin(self):
        return self.getLoginWithGraphQL().json().get("data").get("viewer").get("login")

    def getUser(self):
        logger.debug("Retrieving user informations")
        return self._session.get(f"https://api.github.com/user", auth=self._auth, headers=self._header)

    def getLoginWithGraphQL(self):
        logger.debug("Retrieving identity with GraphQL")

        headers = self._header
        headers["Authorization"] = f"token {self._token}"

        data = {"query": "query UserCurrent{viewer{login}}"}

        return self._session.post("https://api.github.com/graphql", headers=headers, json=data)

    def __paginatedGet(self, url, data="", maxData=0):

        page = 1
        res = []
        while True:

            params = {"page": page}

            response = self._session.get(
                url,
                params=params,
                auth=self._auth,
                headers=self._header,
            ).json()

            if not isinstance(response, list) and response.get("message", None):
                if response.get("message") == "Bad credentials":
                    raise GitHubBadCredentials(response.get("message"))
                elif response.get("message") != "Not Found":
                    raise GitHubError(response.get("message"))
                return res

            if (data != "" and len(response.get(data)) == 0) or (data == "" and len(response) == 0):
                break

            if data != "" and len(response.get(data)) != 0:
                res.extend(response.get(data, []))

            if data == "" and len(response) != 0:
                res.extend(response)

            if maxData != 0 and len(res) >= maxData:
                break

            page += 1

        return res

    def listRepos(self):
        logger.debug("Listing repos")

        if self._isGHSToken:
            url = f"https://api.github.com/orgs/{self._org}/repos"
        else:
            url = f"https://api.github.com/user/repos"

        response = self.__paginatedGet(url)

        for repo in response:
            # filter for specific org
            if self._org:
                if self._org.lower() == repo.get("owner").get("login").lower():
                    self._repos.append(repo.get("full_name"))
            else:
                self._repos.append(repo.get("full_name"))

    def addRepo(self, repo):
        logger.debug(f"Checking repo: {repo}")
        if self._org:
            full_name = self._org + "/" + repo
        else:
            # if no org, must provide repo as 'org/repo'
            # FIXME: This cannot happen at the moment because --org argument is required
            if len(repo.split("/")) == 2:
                full_name = repo
            else:
                # FIXME: Raise an Exception here
                logger.error("Invalid repo name: {repo}")

        response = self._session.get(
            f"{self._repoURL}/{full_name}",
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("message", None) and response.get("message") == "Bad credentials":
            raise GitHubBadCredentials(response.get("message"))

        if response.get("id"):
            self._repos.append(response.get("full_name"))

    def listEnvFromrepo(self, repo):
        logger.debug(f"Listing environment secret from repo: {repo}")
        res = []
        response = self.__paginatedGet(f"{self._repoURL}/{repo}/environments", data="environments")

        for env in response:
            res.append(env.get("name"))
        return res

    def listSecretsFromEnv(self, repo, env):
        logger.debug(f"Getting environment secrets for {repo}: {env}")
        envReq = urllib.parse.quote(env, safe="")
        res = []

        response = self.__paginatedGet(f"{self._repoURL}/{repo}/environments/{envReq}/secrets", data="secrets")

        for sec in response:
            res.append(sec.get("name"))

        return res

    def listSecretsFromRepo(self, repo):
        res = []

        response = self.__paginatedGet(f"{self._repoURL}/{repo}/actions/secrets", data="secrets")

        for sec in response:
            res.append(sec.get("name"))

        return res

    def listOrganizationSecretsFromRepo(self, repo):
        res = []

        response = self.__paginatedGet(f"{self._repoURL}/{repo}/actions/organization-secrets", data="secrets")

        for sec in response:
            res.append(sec.get("name"))

        return res

    def listDependabotSecretsFromRepo(self, repo):
        res = []

        response = self.__paginatedGet(f"{self._repoURL}/{repo}/dependabot/secrets", data="secrets")

        for sec in response:
            res.append(sec.get("name"))

        return res

    def listDependabotOrganizationSecrets(self):
        res = []

        response = self.__paginatedGet(f"https://api.github.com/orgs/{self._org}/dependabot/secrets", data="secrets")

        for sec in response:
            res.append(sec.get("name"))

        return res

    def listEnvProtections(self, repo, env):
        logger.debug("Getting environment protections")
        envReq = urllib.parse.quote(env, safe="")
        res = []
        response = requests.get(
            f"{self._repoURL}/{repo}/environments/{envReq}",
            auth=self._auth,
            headers=self._header,
        ).json()

        for protection in response.get("protection_rules"):
            protectionType = protection.get("type")
            res.append(protectionType)

        return res

    def getEnvDetails(self, repo, env):
        envReq = urllib.parse.quote(env, safe="")
        response = self._session.get(
            f"{self._repoURL}/{repo}/environments/{envReq}",
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("message"):
            raise GitHubError(response.get("message"))
        return response

    def createDeploymentBranchPolicy(self, repo, env):
        envReq = urllib.parse.quote(env, safe="")
        logger.debug(f"Adding new branch policy for {self._branchName} on {envReq}")

        data = {"name": f"{self._branchName}"}
        response = self._session.post(
            f"{self._repoURL}/{repo}/environments/{envReq}/deployment-branch-policies",
            json=data,
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("message"):
            raise GitHubError(response.get("message"))

        policyId = response.get("id")
        logger.debug(f"Branch policy id: {policyId}")
        return policyId

    def deleteDeploymentBranchPolicy(self, repo, env):
        logger.debug("Delete deployment branch policy")
        envReq = urllib.parse.quote(env, safe="")
        response = self._session.get(
            f"{self._repoURL}/{repo}/environments/{envReq}",
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("deployment_branch_policy") is not None:
            response = self._session.get(
                f"{self._repoURL}/{repo}/environments/{envReq}/deployment-branch-policies",
                auth=self._auth,
                headers=self._header,
            ).json()

            for policy in response.get("branch_policies"):
                if policy.get("name").lower() == self._branchName.lower():
                    logger.verbose(f"Deleting branch policy for {self._branchName} on {envReq}")
                    policyId = policy.get("id")
                    self._session.delete(
                        f"{self._repoURL}/{repo}/environments/{envReq}/deployment-branch-policies/{policyId}",
                        auth=self._auth,
                        headers=self._header,
                    )

    def disableBranchProtectionRules(self, repo):
        logger.debug("Modifying branch protection")
        response = self._session.get(
            f"{self._repoURL}/{repo}/branches/{urllib.parse.quote(self._branchName)}",
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("name") and response.get("protected"):
            data = {
                "required_status_checks": None,
                "enforce_admins": False,
                "required_pull_request_reviews": None,
                "restrictions": None,
                "allow_deletions": True,
                "allow_force_pushes": True,
            }
            self._session.put(
                f"{self._repoURL}/{repo}/branches/{urllib.parse.quote(self._branchName)}/protection",
                json=data,
                auth=self._auth,
                headers=self._header,
            )

    def modifyEnvProtectionRules(self, repo, env, wait, reviewers, branchPolicy):
        data = {
            "wait_timer": wait,
            "reviewers": reviewers,
            "deployment_branch_policy": branchPolicy,
        }
        envReq = urllib.parse.quote(env, safe="")
        response = self._session.put(
            f"{self._repoURL}/{repo}/environments/{envReq}",
            json=data,
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("message"):
            raise GitHubError(response.get("message"))
        return response

    def deleteDeploymentBranchPolicyForAllEnv(self, repo):
        allEnv = self.listEnvFromrepo(repo)
        for env in allEnv:
            self.deleteDeploymentBranchPolicy(repo, env)

    def checkBranchProtectionRules(self, repo):
        response = self._session.get(
            f"{self._repoURL}/{repo}/branches/{urllib.parse.quote(self._branchName)}",
            auth=self._auth,
            headers=self._header,
        ).json()
        if response.get("message"):
            raise GitHubError(response.get("message"))
        return response.get("protected")

    def getBranchesProtectionRules(self, repo):
        logger.debug("Getting branch protection rules")
        response = self._session.get(
            f"{self._repoURL}/{repo}/branches/{urllib.parse.quote(self._branchName)}/protection",
            auth=self._auth,
            headers=self._header,
        ).json()
        if response.get("message"):
            return None
        return response

    def updateBranchesProtectionRules(self, repo, protections):
        logger.debug("Updating branch protection rules")

        response = self._session.put(
            f"{self._repoURL}/{repo}/branches/{urllib.parse.quote(self._branchName)}/protection",
            auth=self._auth,
            headers=self._header,
            json=protections,
        ).json()

        return response

    def cleanDeploymentsLogs(self, repo):
        logger.verbose(f"Cleaning deployment logs from: {repo}")
        url = f"{self._repoURL}/{repo}/deployments?ref={urllib.parse.quote(self._branchName)}"
        response = self.__paginatedGet(url, maxData=200)

        for deployment in response:
            if not self._isGHSToken and deployment.get("creator").get("login").lower() != self._githubLogin.lower():
                continue

            commit = self._session.get(
                f"{self._repoURL}/{repo}/commits/{deployment['sha']}", auth=self._auth, headers=self._header
            ).json()

            # We want to delete only our action so we must filter some attributes
            if commit["commit"]["message"] not in [Git.ATTACK_COMMIT_MSG, Git.CLEAN_COMMIT_MSG]:
                continue

            if commit["commit"]["committer"]["name"] != Git.USER:
                continue

            if commit["commit"]["committer"]["email"] != Git.EMAIL:
                continue

            deploymentId = deployment.get("id")
            data = {"state": "inactive"}
            self._session.post(
                f"{self._repoURL}/{repo}/deployments/{deploymentId}/statuses",
                json=data,
                auth=self._auth,
                headers=self._header,
            )
            self._session.delete(
                f"{self._repoURL}/{repo}/deployments/{deploymentId}",
                auth=self._auth,
                headers=self._header,
            )

    def cleanRunLogs(self, repo, workflowFilename):
        logger.verbose(f"Cleaning run logs from: {repo}")
        url = f"{self._repoURL}/{repo}/actions/runs?branch={urllib.parse.quote(self._branchName)}"

        if not self._isGHSToken:
            url += f"&actor={self._githubLogin.lower()}"

        # we dont scan for all the logs we only check the last 200
        response = self.__paginatedGet(url, data="workflow_runs", maxData=200)

        for run in response:

            # skip if it's not our commit
            if run.get("head_commit").get("message") not in [Git.ATTACK_COMMIT_MSG, Git.CLEAN_COMMIT_MSG]:
                continue

            committer = run.get("head_commit").get("committer")
            if committer.get("name") != Git.USER:
                continue

            if committer.get("email") != Git.EMAIL:
                continue

            runId = run.get("id")
            status = (
                self._session.get(
                    f"{self._repoURL}/{repo}/actions/runs/{runId}",
                    json={},
                    auth=self._auth,
                    headers=self._header,
                )
                .json()
                .get("status")
            )

            if status != "completed":
                self._session.post(
                    f"{self._repoURL}/{repo}/actions/runs/{runId}/cancel",
                    json={},
                    auth=self._auth,
                    headers=self._header,
                )
                status = (
                    self._session.get(
                        f"{self._repoURL}/{repo}/actions/runs/{runId}",
                        json={},
                        auth=self._auth,
                        headers=self._header,
                    )
                    .json()
                    .get("status")
                )
                if status != "completed":
                    for i in range(self._maxRetry):
                        time.sleep(2)
                        status = (
                            self._session.get(
                                f"{self._repoURL}/{repo}/actions/runs/{runId}",
                                json={},
                                auth=self._auth,
                                headers=self._header,
                            )
                            .json()
                            .get("status")
                        )
                        if status == "completed":
                            break

            self._session.delete(
                f"{self._repoURL}/{repo}/actions/runs/{runId}/logs",
                auth=self._auth,
                headers=self._header,
            )
            self._session.delete(
                f"{self._repoURL}/{repo}/actions/runs/{runId}",
                auth=self._auth,
                headers=self._header,
            )

    def cleanAllLogs(self, repo, workflowFilename):
        logger.debug(f"Cleaning logs for: {repo}")
        self.cleanRunLogs(repo, workflowFilename)
        self.cleanDeploymentsLogs(repo)

    def createWorkflowOutputDir(self, repo):
        outputName = repo.split("/")
        makedirs(f"{self._outputDir}/{outputName[0]}/{outputName[1]}", exist_ok=True)

    def waitWorkflow(self, repo, workflowFilename):
        logger.info("Getting workflow output")

        time.sleep(5)
        workflowFilename = urllib.parse.quote_plus(workflowFilename)
        response = self._session.get(
            f"{self._repoURL}/{repo}/actions/workflows/{workflowFilename}/runs?branch={urllib.parse.quote(self._branchName)}",
            auth=self._auth,
            headers=self._header,
        ).json()

        if response.get("total_count", 0) == 0:
            for i in range(self._maxRetry):
                logger.warning(f"Workflow not started, sleeping for {self._sleepTime}s")
                time.sleep(self._sleepTime)
                response = self._session.get(
                    f"{self._repoURL}/{repo}/actions/workflows/{workflowFilename}/runs?branch={urllib.parse.quote(self._branchName)}",
                    auth=self._auth,
                    headers=self._header,
                ).json()
                if response.get("total_count", 0) != 0:
                    break
                if i == (self._maxRetry - 1):
                    logger.error("Error: workflow still not started.")
                    return None, None

        if response.get("workflow_runs")[0].get("status") != "completed":
            for i in range(self._maxRetry):
                logger.warning(f"Workflow not finished, sleeping for {self._sleepTime}s")
                time.sleep(self._sleepTime)
                response = self._session.get(
                    f"{self._repoURL}/{repo}/actions/workflows/{workflowFilename}/runs?branch={urllib.parse.quote(self._branchName)}",
                    auth=self._auth,
                    headers=self._header,
                ).json()
                if response.get("workflow_runs")[0].get("status") == "completed":
                    break
                if i == (self._maxRetry - 1):
                    logger.error("Error: workflow still not finished.")

        return (
            response.get("workflow_runs")[0].get("id"),
            response.get("workflow_runs")[0].get("conclusion"),
        )

    def downloadWorkflowOutput(self, repo, name, workflowId):
        self.createWorkflowOutputDir(repo)

        zipFile = self._session.get(
            f"{self._repoURL}/{repo}/actions/runs/{workflowId}/logs",
            auth=self._auth,
            headers=self._header,
        )

        date = time.strftime("%Y-%m-%d_%H-%M-%S")
        with open(f"{self._outputDir}/{repo}/workflow_{name}_{date}.zip", "wb") as f:
            f.write(zipFile.content)
        f.close()
        return f"workflow_{name}_{date}.zip"

    def getFailureReason(self, repo, workflowId):
        res = []
        workflow = self._session.get(
            f"{self._repoURL}/{repo}/actions/runs/{workflowId}",
            auth=self._auth,
            headers=self._header,
        ).json()
        checkSuiteId = workflow.get("check_suite_id")
        checkRuns = self._session.get(
            f"{self._repoURL}/{repo}/check-suites/{checkSuiteId}/check-runs",
            auth=self._auth,
            headers=self._header,
        ).json()

        if checkRuns.get("total_count"):
            for checkRun in checkRuns.get("check_runs"):
                checkRunId = checkRun.get("id")
                annotations = self._session.get(
                    f"{self._repoURL}/{repo}/check-runs/{checkRunId}/annotations",
                    auth=self._auth,
                    headers=self._header,
                ).json()
                for annotation in annotations:
                    res.append(annotation.get("message"))
        return res

    def filterWriteRepos(self):
        res = []
        for repo in self._repos:
            try:
                self.listSecretsFromRepo(repo)
                res.append(repo)
            except GitHubError:
                pass
        self._repos = res

    def isGHSToken(self):
        return self._isGHSToken
