from bouncer.constants import MANAGE, READ, CREATE, EDIT
from flask import Blueprint, current_app
from flask.ext.restful import Resource, marshal_with, marshal, reqparse
from flask_login import login_required, current_user
from sqlalchemy import exc
from sqlalchemy.orm import joinedload

from . import dataformat
from .authorization import require
from .core import db, event
from .models import Courses, UserTypesForCourse, CoursesAndUsers
from .util import pagination, new_restful_api, get_model_changes

courses_api = Blueprint('courses_api', __name__)
api = new_restful_api(courses_api)

new_course_parser = reqparse.RequestParser()
new_course_parser.add_argument('name', type=str, required=True, help='Course name is required.')
new_course_parser.add_argument('description', type=str)
new_course_parser.add_argument('enable_student_create_questions', type=bool)
new_course_parser.add_argument('enable_student_create_tags', type=bool)

# parser copy() has not been pushed into stable release yet, so we have to wait till then to
# use it, it'll save duplicate code since these two parsers are pretty much identical
# existing_course_parser = new_course_parser.copy()
existing_course_parser = reqparse.RequestParser()
existing_course_parser.add_argument('id', type=int, required=True, help='Course id is required.')
existing_course_parser.add_argument('name', type=str, required=True, help='Course name is required.')
existing_course_parser.add_argument('description', type=str)
existing_course_parser.add_argument('enable_student_create_questions', type=bool, default=False)
existing_course_parser.add_argument('enable_student_create_tags', type=bool, default=False)

# events
on_course_modified = event.signal('COURSE_MODIFIED')
on_course_get = event.signal('COURSE_GET')
on_course_list_get = event.signal('COURSE_LIST_GET')
on_course_create = event.signal('COURSE_CREATE')


# /
class CourseListAPI(Resource):
    @login_required
    @pagination(Courses)
    @marshal_with(dataformat.get_courses())
    def get(self, objects):
        require(MANAGE, Courses)
        on_course_list_get.send(
            self,
            event_name=on_course_list_get.name,
            user=current_user)
        return objects

    @login_required
    def post(self):
        """
        Create new course
        :return:
        """
        require(CREATE, Courses)
        params = new_course_parser.parse_args()
        new_course = Courses(
            name=params.get("name"),
            description=params.get("description", None),
            enable_student_create_questions=params.get("enable_student_create_questions", False),
            enable_student_create_tags=params.get("enable_student_create_tags", False)
        )
        try:
            # create the course
            db.session.add(new_course)
            # also need to enrol the user as an instructor
            instructor_role = UserTypesForCourse.query \
                .filter_by(name=UserTypesForCourse.TYPE_INSTRUCTOR).first()
            new_courseanduser = CoursesAndUsers(
                course=new_course, users_id=current_user.id, usertypeforcourse=instructor_role)
            db.session.add(new_courseanduser)
            db.session.commit()

            on_course_create.send(
                self,
                event_name=on_course_create.name,
                user=current_user,
                data=marshal(new_course, dataformat.get_courses()))

        except exc.IntegrityError:
            db.session.rollback()
            current_app.logger.error("Failed to add new course. Duplicate.")
            return {"error": "A course with the same name already exists."}, 400
        except exc.SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error("Failed to add new course. " + str(e))
            raise
        return marshal(new_course, dataformat.get_courses())


api.add_resource(CourseListAPI, '')


# /id
class CourseAPI(Resource):
    @login_required
    def get(self, course_id):
        course = Courses.query.\
            options(joinedload("_criteriaandcourses").joinedload("criterion")).\
            get_or_404(course_id)
        require(READ, course)
        on_course_get.send(
            self,
            event_name=on_course_get.name,
            user=current_user,
            data={'id': course_id})
        return marshal(course, dataformat.get_courses())

    @login_required
    def post(self, course_id):
        """
        Update a course

        :param course_id:
        :return:
        """
        course = Courses.query.get_or_404(course_id)
        require(EDIT, course)
        params = existing_course_parser.parse_args()
        # make sure the course id in the url and the course id in the params match
        if params['id'] != course_id:
            return {"error": "Course id does not match URL."}, 400
        # modify course according to new values, preserve original values if values not passed
        course.name = params.get("name", course.name)
        course.description = params.get("description", course.description)
        course.enable_student_create_questions = params.get(
            "enable_student_create_questions",
            course.enable_student_create_questions)
        course.enable_student_create_tags = params.get(
            "enable_student_create_tags",
            course.enable_student_create_tags)
        on_course_modified.send(
            self,
            event_name=on_course_modified.name,
            user=current_user,
            data=get_model_changes(course))
        db.session.commit()
        return marshal(course, dataformat.get_courses())

api.add_resource(CourseAPI, '/<int:course_id>')
