from launchpadlib.launchpad import Launchpad

STATUSES_FOR_CHECK = ["Incomplete", "Confirmed", "New"]
CHECKS = {
    "version": ["iso", "env", "version"],
    "expected result": ["expected"],
    "steps to reproduce": ["steps"],
    "actual result": ["actual", "observed"]
}
SUBJECT = 'Autochecker'
MESSAGE_FOR_INCOMPLETE = (
    "(This check performed automatically)\n"
    "Please, make sure that bug description contains the following sections "
    "filled in with the appropriate data related to the bug you are "
    "describing: \n\n%s\n\n"
    "For more detailed information on the contents of each of the listed "
    "sections see https://wiki.openstack.org/wiki/Fuel/How_to_contribute#"
    "Here_is_how_you_file_a_bug\n")

SKIP_TAGS = ['docs', 'area-docs', 'area-build', 'area-ci', 'area-devops',
             'area-infra-apps', 'area-qa', 'covered-by-bp', 'feature',
             'fuel-devops', 'need-bp', 'non-release', 'system-tests',
             'tech-debt', 'enhancement']
TAG = 'need-info'


cache_dir = '~/.launchpad/autocheck'
lp = Launchpad.login_with('autocheck', 'production', cache_dir)


def _check_bug(bug):
    print "Checking of %s\n" % bug.web_link
    incomplete = []
    for check in CHECKS:
        current_check = CHECKS[check]
        correct = False
        for field in current_check:
            if field in bug.description.lower():
                correct = True
        if not correct:
            incomplete.append("%s\n" % check)
    if not incomplete:
        if TAG in bug.tags:
            _remove_tag(bug)
    else:
        if TAG not in bug.tags:
            _add_tag(bug)
            _post_comment(bug, incomplete)


def _generate_string(array_fields):
    msg = ''
    for field in array_fields:
        msg += '%s\n' % field
    return MESSAGE_FOR_INCOMPLETE % msg


# launchpadlib cannot working with tags like tuples
def _add_tag(bug):
    bug.tags = bug.tags + [TAG]
    bug.lp_save()
    print "Tag added to %s\n" % bug.web_link


def _remove_tag(bug):
    tags = bug.tags
    if TAG in tags:
        tags.remove(TAG)
        bug.tags = tags
        bug.lp_save()
        print "Tag removed from %s\n" % bug.web_link


def _post_comment(bug, fields):
    flag_comment = False
    for comment in range(1, bug.message_count):
        if bug.messages[comment].subject is SUBJECT:
            flag_comment = True
    if not flag_comment:
        print "Comment added to %s\n" % bug.web_link
        bug.newMessage(subject=SUBJECT,
                       content=_generate_string(fields))


def get_project_bugs(project_name, milestones=[]):
    print "\n\nGetting project %s...\n\n" % project_name
    project = lp.projects[project_name]
    for milestone in milestones:
        current_milestone = project.getMilestone(
            name=milestone)
        bugs_for_checking = project.searchTasks(
            milestone=current_milestone, status=STATUSES_FOR_CHECK)
        for bug_task in bugs_for_checking:
            skip = False
            for tag in bug_task.bug.tags:
                if tag in SKIP_TAGS:
                    _remove_tag(bug_task.bug)
                    skip = True
            if not skip:
                _check_bug(bug_task.bug)


if __name__=='__main__':
    test_milestone = ['9.0']
    get_project_bugs("fuel", test_milestone)
    get_project_bugs("mos", test_milestone)
