from launchpadlib.launchpad import Launchpad

STATUSES_FOR_CHECK = ["Incomplete", "Confirmed", "New"]
CHECKS = ["iso", "env", "expected result", "actual result"]
SUBJECT = 'Autochecker'
MESSAGE_FOR_INCOMPLETE = (
    "Attention: \n"
    "field 'Further information' needs corrections as it contains not all "
    "the data required for effective reproducing, investigation, and fixing "
    "the issue you reported. \n"
    "Please, make sure that this field contains the following sections filled "
    "in with the appropriate data related to the bug you are describing: \n\n"
    "Detailed bug description:\n"
    " <put your information here>\n"
    "Steps to reproduce:\n"
    " <put your information here>\n"
    "Expected results:\n"
    " <put your information here>\n"
    "Actual result:\n"
    " <put your information here>\n"
    "Reproducibility:\n"
    " <put your information here>\n"
    "Workaround:\n"
    " <put your information here>\n"
    "Impact:\n"
    " <put your information here>\n"
    "Description of the environment: \n"
    "- Operation system: <put your information here>\n"
    "- Versions of components: <put your information here>\n"
    "- Reference architecture: <put your information here>\n"
    "- Network model: <put your information here>\n"
    "- Related projects installed: <put your information here>\n"
    "Additional information:\n"
    " <put your information here>\n\n"
    "For more detailed information on the contents of each of the listed "
    "sections see https://wiki.openstack.org/wiki/Fuel/How_to_contribute#"
    "Here_is_how_you_file_a_bug\n"
    "Remember: lack of provided information will lead to decreasing priority "
    "of the bug and substantial delays with defect fixing.\n")


TAG = 'need-info'


cache_dir = '~/.launchpad/autocheck'
lp = Launchpad.login_with('autocheck', 'production', cache_dir)


def _check_bug(bug):
    check_flag = True
    for check in CHECKS:
        if check not in bug.description.lower():
            check_flag = False
    if check_flag:
        if TAG in bug.tags:
            # launchpadlib cannot working with tags like tuples
            tags = bug.tags
            tags.remove(TAG)
            bug.tags = tags
            bug.lp_save()
    else:
        if TAG not in bug.tags:
            # launchpadlib cannot working with tags like tuples
            bug.tags = bug.tags + [TAG]
            bug.lp_save()
        flag_comment = False
        for comment in range(1, bug.message_count):
            if bug.messages[comment].subject is SUBJECT:
                flag_comment = True
        if not flag_comment:
            bug.newMessage(subject=SUBJECT,
                           content=MESSAGE_FOR_INCOMPLETE)

def get_project_bugs(project_name, milestones=[]):
    project = lp.projects[project_name]
    for milestone in milestones:
        current_milestone = project.getMilestone(
            name=milestone)
        bugs_for_checking = project.searchTasks(
            milestone=current_milestone, status=STATUSES_FOR_CHECK)
        for bug_task in bugs_for_checking:
            import pdb; pdb.set_trace()
            _check_bug(bug_task.bug)

get_project_bugs("test-autochecker", ["first-m"])
