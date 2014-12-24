from bouncer.constants import MANAGE
from flask import Blueprint, Flask, request, current_app
from flask.ext.login import login_required, current_user
from flask.ext.restful import Resource, reqparse, marshal
from sqlalchemy import func

from .authorization import allow, require
from . import dataformat
from .core import event
from .models import PostsForQuestions, CoursesAndUsers, Courses, Posts, PostsForAnswers, UserTypesForCourse,\
				Judgements, AnswerPairings, PostsForAnswersAndPostsForComments, PostsForComments,\
				CriteriaAndPostsForQuestions, GroupsAndUsers, Groups
from .util import new_restful_api

import csv, os, time
from .classlist import random_generator

report_api = Blueprint('report_api', __name__)
api = new_restful_api(report_api)

# TODO put in config file
UPLOAD_FOLDER = os.getcwd() + '/acj/static/report'
app = Flask(__name__)
app.config['PERMANENT_REPORT_UPLOAD_FOLDER'] = UPLOAD_FOLDER

report_parser = reqparse.RequestParser()
report_parser.add_argument('group_id', type=int)
# may change 'type' to int
report_parser.add_argument('type', type=str, required=True)
report_parser.add_argument('assignment', type=int)

#events
on_export_report = event.signal('EXPORT_REPORT')
# should we have a different event for each type of report?

def name_generator(course, report_name, group_id, file_type="csv"):
	date = time.strftime("%Y-%m-%d--%H-%M-%S")
	group_name = ""
	if group_id:
		group_name = Groups.query.get_or_404(group_id).name
		group_name += '-'
	#return report_name + "_" + course.name + "_" + random_generator(4) + "." + file_type
	return course.name + "-" + group_name + report_name + "--" + date + "." + file_type

class ReportRootAPI(Resource):
	@login_required
	def post(self, course_id):
		course = Courses.query.get_or_404(course_id)
		post = Posts(courses_id=course.id)
		question = PostsForQuestions(post=post)
		require(MANAGE, question)

		params = report_parser.parse_args()
		group_id = params.get('group_id', None)
		type = params.get('type')
		assignment = params.get('assignment', None)

		if type=="participation_stat":
			if assignment:
				question = PostsForQuestions.query.get_or_404(assignment)
				questions = [question]
				data = participation_stat_report(course_id, questions, group_id, False)
			else:
				questions = PostsForQuestions.query.join(Posts).filter_by(courses_id=course_id).all()
				data = participation_stat_report(course_id, questions, None, True)

			title = ['Question', 'Username', 'Last Name', 'First Name', 'Answer Submitted', 'Answer ID',
					 'Evaluations Submitted', 'Evaluations Required', 'Evaluation Requirements Met',
					 'Replies Submitted']
			titles =[title]
		elif type=="participation":
			user_titles = ['Last Name', 'First Name', 'Student No']
			if assignment:
				question = PostsForQuestions.query.filter_by(id=assignment).join(Posts).filter_by(courses_id=course_id).first_or_404()
				questions = [question]
			else:
				questions = PostsForQuestions.query.join(Posts).filter_by(courses_id=course_id)\
					.order_by(PostsForQuestions.answer_start).all()
			data = participation_report(course_id, questions, group_id)

			title_row1 = ["" for x in user_titles]
			title_row2 = user_titles
			for q in questions:
				criteria = CriteriaAndPostsForQuestions.query.filter_by(postsforquestions_id=q.id, active=True).all()
				title_row1 += [q.title] + ["" for x in criteria]
				for c in criteria:
					title_row2.append('Percentage Score for "' + c.criterion.name + '"')
				title_row2.append("Evaluations Submitted ("+str(q.num_judgement_req)+' required)')
				if q.selfevaltype_id:
					title_row1 += [""]
					title_row2.append("Self Evaluation Submitted")
			titles = [title_row1, title_row2]

		else:
			return {'error': 'The requested report type cannot be found'}, 400

		name = name_generator(course, type, group_id)
		tmpName = os.path.join(current_app.config['REPORT_FOLDER'], name)

		report = open(tmpName, 'wb')
		out = csv.writer(report)
		for t in titles:
			out.writerow(t)
		for s in data:
			out.writerow(s)
		report.close()

		on_export_report.send(
			current_app._get_current_object(),
			event_name=on_export_report.name,
			user=current_user,
			course_id=course_id,
			data={'type': type, 'filename': name})

		return {'file': 'report/'+name}
api.add_resource(ReportRootAPI, '')

def participation_stat_report(course_id, assignments, group_id, overall):
	report = []
	student = UserTypesForCourse.query.filter_by(name=UserTypesForCourse.TYPE_STUDENT).first().id
	classlist = CoursesAndUsers.query.filter_by(courses_id=course_id).\
		filter(CoursesAndUsers.usertypesforcourse_id==student).all()
	if group_id:
		userIds = [u.users_id for u in classlist]
		classlist = GroupsAndUsers.query.filter_by(groups_id=group_id, active=True)\
			.filter(GroupsAndUsers.users_id.in_(userIds)).all()

	total_req = 0
	total = {}

	for ques in assignments:
		# ANSWERS: assume max one answer per user
		answers = PostsForAnswers.query.filter_by(postsforquestions_id=ques.id).all()
		answers = {a.users_id: a.id for a in answers}
		# EVALUATIONS
		evaluations = Judgements.query.with_entities(Judgements.users_id, func.count(Judgements.id)).\
			join(AnswerPairings).filter_by(postsforquestions_id=ques.id).group_by(Judgements.users_id).all()
		evaluations = {usersId: count for (usersId, count) in evaluations}
		# COMMENTS
		comments = PostsForAnswersAndPostsForComments.query.\
			join(PostsForAnswers).filter(PostsForAnswers.postsforquestions_id==ques.id).\
			join(PostsForComments, Posts).\
			with_entities(Posts.users_id, func.count(PostsForAnswersAndPostsForComments.id)).\
			group_by(Posts.users_id).all()
		comments = {usersId: count for (usersId, count) in comments}
		total_req += ques.num_judgement_req	# for overall required
		criteria_count = len(ques.criteria)
		for student in classlist:
			user = student.user
			temp = [ques.title, user.username, user.lastname, user.firstname]

			# OVERALL
			if user.id not in total:
				total[user.id] = {
					'total_answers': 0,
					'total_evaluations': 0,
					'total_comments': 0
				}

			submitted = 1 if user.id in answers else 0
			answerId = answers[user.id] if submitted else 'N/A'
			total[user.id]['total_answers'] += submitted
			temp.extend([submitted, answerId])

			evalSubmitted = evaluations[user.id] if user.id in evaluations else 0
			evalSubmitted = evalSubmitted / criteria_count
			evalReqMet = 'Yes' if evalSubmitted >= ques.num_judgement_req else 'No'
			total[user.id]['total_evaluations'] += evalSubmitted
			temp.extend([evalSubmitted, ques.num_judgement_req, evalReqMet])

			commentCount = comments[user.id] if user.id in comments else 0
			total[user.id]['total_comments'] += commentCount
			temp.append(commentCount)

			report.append(temp)

	if overall:
		for student in classlist:
			user = student.user
			sum = total[user.id]
			# assume a user can only at most do the required number
			req_met = 'Yes' if sum['total_evaluations'] >= total_req else 'No'
			temp = ['(Overall in Course)', user.id, user.lastname, user.firstname,
					sum['total_answers'], '(Overall in Course)',
					sum['total_evaluations'], total_req, req_met,
					sum['total_comments']]
			report.append(temp)
	return report

def participation_report(course_id, questions, group_id):
	report = []
	student = UserTypesForCourse.query.filter_by(name=UserTypesForCourse.TYPE_STUDENT).first().id
	classlist = CoursesAndUsers.query.filter_by(courses_id=course_id).\
		filter(CoursesAndUsers.usertypesforcourse_id==student).all()
	if group_id:
		userIds = [u.users_id for u in classlist]
		classlist = GroupsAndUsers.query.filter_by(groups_id=group_id, active=True)\
			.filter(GroupsAndUsers.users_id.in_(userIds)).all()

	quesIds = [q.id for q in questions]
	userIds = [u.user.id for u in classlist]

	# ANSWERS - scores
	answers = PostsForAnswers.query.filter(PostsForAnswers.postsforquestions_id.in_(quesIds)) \
		.join(Posts).filter(Posts.users_id.in_(userIds)).all()

	scores = {}		# structure - userId/quesId/criteriaandpostsforquestions_id/normalized_score
	for ans in answers:
		if ans.users_id not in scores:
			scores[ans.users_id] = {}
		if ans.postsforquestions_id not in scores[ans.users_id]:
			scores[ans.users_id][ans.postsforquestions_id] = {}
		for s in ans._scores:
			scores[ans.users_id][ans.postsforquestions_id][s.criteriaandpostsforquestions_id] = s.normalized_score

	# COMPARISONS
	comparisons = Judgements.query.filter(Judgements.users_id.in_(userIds)) \
		.join(AnswerPairings).filter(AnswerPairings.postsforquestions_id.in_(quesIds)) \
		.with_entities(AnswerPairings.postsforquestions_id, Judgements.users_id,
					   func.count(Judgements.id)) \
		.group_by(AnswerPairings.postsforquestions_id, Judgements.users_id).all()

	judgements = {}		# structure - userId/quesId/count
	for (quesId, userId, count) in comparisons:
		judgements.setdefault(userId, {}).setdefault(quesId, 0)
		judgements[userId][quesId] = count

	# CRITERIA
	criteriaandpostsforquestions = CriteriaAndPostsForQuestions.query \
		.filter(CriteriaAndPostsForQuestions.postsforquestions_id.in_(quesIds)) \
		.filter_by(active=True).order_by(CriteriaAndPostsForQuestions.id).all()

	criteria = {}	# structure - quesId/criterionId
	for criterion in criteriaandpostsforquestions:
		criteria.setdefault(criterion.postsforquestions_id, [])
		criteria[criterion.postsforquestions_id].append(criterion.id)

	# SELF-EVALUATION - assuming no comparions
	selfeval = PostsForAnswersAndPostsForComments.query.filter_by(selfeval=True) \
		.join(PostsForAnswers).filter(PostsForAnswers.postsforquestions_id.in_(quesIds)) \
		.join(PostsForComments, Posts).filter(Posts.users_id.in_(userIds)) \
		.with_entities(PostsForAnswers.postsforquestions_id, Posts.users_id,
					   func.count(PostsForAnswersAndPostsForComments.id)) \
		.group_by(PostsForAnswers.postsforquestions_id, Posts.users_id).all()

	comments = {}	# structure - userId/quesId/count
	for (quesId, userId, count) in selfeval:
		comments.setdefault(userId, {}).setdefault(quesId, 0)
		comments[userId][quesId] = count

	for coursesanduser in classlist:
		user = coursesanduser.user
		temp = [user.lastname, user.firstname, user.student_no]

		for ques in questions:
			for criterion in criteria[ques.id]:
				if user.id not in scores or ques.id not in scores[user.id]:
					score = 'No Answer'
				elif criterion not in scores[user.id][ques.id]:
					score = 'Not Evaluated'
				else:
					score = scores[user.id][ques.id][criterion]
				temp.append(score)
			if user.id not in judgements or ques.id not in judgements[user.id]:
				judged = 0
			else:
				judged = judgements[user.id][ques.id] / len(criteria[ques.id])
			temp.append(str(judged))
			# self-evaluation
			if ques.selfevaltype_id:
				if user.id not in comments or ques.id not in comments[user.id]:
					temp.append(0)
				else:
					temp.append(comments[user.id][ques.id])
		report.append(temp)

	return report