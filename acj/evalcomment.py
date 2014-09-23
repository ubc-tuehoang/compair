from flask import Blueprint, current_app
from flask.ext.login import login_required, current_user
from flask.ext.restful import Resource, marshal
from flask.ext.restful.reqparse import RequestParser
from bouncer.constants import EDIT, CREATE, MANAGE

from . import dataformat
from .core import db, event
from .models import Judgements, PostsForComments, PostsForJudgements, Courses, PostsForQuestions, Posts, \
	AnswerPairings, CoursesAndUsers, CriteriaAndCourses
from .util import new_restful_api
from .authorization import allow, require

evalcomments_api = Blueprint('evalcomments_api', __name__)
api = new_restful_api(evalcomments_api)

new_comment_parser = RequestParser()
new_comment_parser.add_argument('judgements', type=list, required=True)

# events
on_evalcomment_create = event.signal('EVALCOMMENT_CREATE')


# /
class EvalCommentRootAPI(Resource):
	@login_required
	def get(self, course_id, question_id):
		course = Courses.query.get_or_404(course_id)
		question = PostsForQuestions.query.get_or_404(question_id)
		post = Posts(courses_id=course_id)
		comment = PostsForComments(post=post)
		judgementComment = PostsForJudgements(postsforcomments=comment)
		require(MANAGE, judgementComment)
		comments = PostsForJudgements.query.join(PostsForComments, Posts).filter(Posts.courses_id==course.id)\
			.join(Judgements, AnswerPairings).filter_by(postsforquestions_id=question.id).all()
		restrict_users = not allow(EDIT, CoursesAndUsers(courses_id=course.id))

		return {'comments': marshal(comments, dataformat.getPostsForJudgements(restrict_users))}
	@login_required
	def post(self, course_id, question_id):
		course = Courses.query.get_or_404(course_id)
		PostsForQuestions.query.get_or_404(question_id)
		criteriaAndCourses = CriteriaAndCourses(courses_id=course.id)
		judgements = Judgements(course_criterion=criteriaAndCourses)
		require(CREATE, judgements)
		params = new_comment_parser.parse_args()
		judgements = params['judgements']
		results = []
		for judgement in params['judgements']:
			judge = Judgements.query.get_or_404(judgement['id'])
			post = Posts(courses_id=course_id)
			post.content = judgement['comment'];
			post.users_id = current_user.id
			comment = PostsForComments(post=post)
			evalcomment = PostsForJudgements(postsforcomments=comment, judgements_id=judge.id)
			db.session.add(post)
			db.session.add(comment)
			db.session.add(evalcomment)
			db.session.commit()
			results.append(evalcomment)

		on_evalcomment_create.send(
			current_app._get_current_object(),
			event_name=on_evalcomment_create.name,
			user=current_user,
			course_id=course_id,
			data=marshal(results, dataformat.getPostsForJudgements(False)))

		return {'objects': marshal(results, dataformat.getPostsForJudgements())}
api.add_resource(EvalCommentRootAPI, '')
