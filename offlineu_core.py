#!/usr/bin/env python3
"""
OfflineU - Self-hosted Course Viewer & Tracker
Enhanced version with dynamic subdirectory navigation
"""

import os
import json
import mimetypes
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any, Tuple
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'

# Supported file types
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.flv', '.wmv'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}
SUBTITLE_EXTENSIONS = {'.srt', '.vtt', '.ass', '.sub', '.sbv'}
TEXT_EXTENSIONS = {'.txt', '.md', '.html', '.htm', '.pdf', '.docx', '.doc', '.rtf'}
QUIZ_INDICATORS = {'quiz', 'exam', 'test', 'assessment', 'exercise', 'assignment', 'homework'}


@dataclass
class Lesson:
    title: str
    path: str
    lesson_type: str  # 'video', 'audio', 'text', 'quiz', 'mixed'
    video_file: Optional[str] = None
    audio_file: Optional[str] = None
    subtitle_file: Optional[str] = None
    text_files: List[str] = None
    completed: bool = False
    last_accessed: Optional[str] = None
    progress_seconds: int = 0
    order: int = 0

    def __post_init__(self):
        if self.text_files is None:
            self.text_files = []


@dataclass
class DirectoryNode:
    """Represents a directory in the course structure"""
    name: str
    path: str
    type: str  # 'directory' or 'lesson'
    children: Dict[str, 'DirectoryNode'] = None
    lessons: List[Lesson] = None
    completed: bool = False
    last_accessed: Optional[str] = None
    order: int = 0
    has_content: bool = False  # Whether this directory contains actual lesson content

    def __post_init__(self):
        if self.children is None:
            self.children = {}
        if self.lessons is None:
            self.lessons = []


@dataclass
class Course:
    name: str
    path: str
    root_node: DirectoryNode
    progress_file: str
    last_accessed_path: Optional[str] = None
    completion_percentage: float = 0.0

    def __post_init__(self):
        if self.root_node is None:
            self.root_node = DirectoryNode("", "", "directory")


class DynamicCourseParser:
    """Enhanced parser that builds a proper directory tree structure"""

    @staticmethod
    def scan_directory(course_path: str) -> Course:
        """Scan directory and build dynamic tree structure"""
        course_path = Path(course_path)
        if not course_path.exists() or not course_path.is_dir():
            raise ValueError(f"Invalid course path: {course_path}")

        course_name = course_path.name
        print(f"Scanning course: {course_name}")

        # Build the directory tree
        root_node = DynamicCourseParser._build_directory_tree(course_path, course_path)
        
        # Calculate completion statistics
        stats = DynamicCourseParser._calculate_completion_stats(root_node)
        
        progress_file = str(course_path / ".offlineu_progress.json")

        return Course(
            name=course_name,
            path=str(course_path),
            root_node=root_node,
            progress_file=progress_file
        )

    @staticmethod
    def _build_directory_tree(course_path: Path, current_path: Path, depth: int = 0) -> DirectoryNode:
        """Recursively build directory tree structure"""
        if depth > 10:  # Prevent infinite recursion
            return DirectoryNode(current_path.name, str(current_path), "directory")

        node_name = current_path.name if current_path != course_path else "Course Root"
        node = DirectoryNode(
            name=node_name,
            path=str(current_path),
            type="directory",
            order=depth
        )

        try:
            # Get all items in current directory
            items = sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            
            for item in items:
                if item.name.startswith('.'):
                    continue
                
                if item.is_dir():
                    # Recursively process subdirectory
                    child_node = DynamicCourseParser._build_directory_tree(course_path, item, depth + 1)
                    if child_node.has_content or child_node.children:
                        node.children[child_node.name] = child_node
                        node.has_content = True
                
                elif item.is_file():
                    # Process file as potential lesson content
                    lesson = DynamicCourseParser._create_lesson_from_file(item, course_path)
                    if lesson:
                        # Add lesson directly to this node's lessons list
                        node.lessons.append(lesson)
                        node.has_content = True

        except (PermissionError, OSError) as e:
            print(f"Error accessing {current_path}: {e}")

        return node

    @staticmethod
    def _create_lesson_from_file(file_path: Path, course_path: Path) -> Optional[Lesson]:
        """Create a lesson from a single file"""
        ext = file_path.suffix.lower()
        filename = file_path.name.lower()

        # Skip non-content files
        if ext in {'.log', '.tmp', '.bak', '.swp', '.DS_Store', '.Thumbs.db'}:
            return None

        # Determine lesson type and files
        video_file = None
        audio_file = None
        subtitle_file = None
        text_files = []
        lesson_type = 'text'

        # Create relative path for file serving - normalize to forward slashes
        relative_path = str(file_path.relative_to(course_path)).replace('\\', '/')

        if ext in VIDEO_EXTENSIONS:
            video_file = relative_path
            lesson_type = 'video'
        elif ext in AUDIO_EXTENSIONS:
            audio_file = relative_path
            lesson_type = 'audio'
        elif ext in SUBTITLE_EXTENSIONS:
            subtitle_file = relative_path
            return None  # Don't create lessons for subtitle files alone
        elif ext in TEXT_EXTENSIONS:
            text_files.append(relative_path)
            if any(indicator in filename for indicator in QUIZ_INDICATORS):
                lesson_type = 'quiz'
        else:
            # Skip unsupported file types
            return None

        # Clean up lesson name for display
        display_name = DynamicCourseParser._clean_lesson_name(file_path.stem)

        return Lesson(
            title=display_name,
            path=str(file_path),  # Store the actual file path, not just parent
            lesson_type=lesson_type,
            video_file=video_file,
            audio_file=audio_file,
            subtitle_file=subtitle_file,
            text_files=text_files,
            order=0
        )

    @staticmethod
    def _clean_lesson_name(name: str) -> str:
        """Clean up lesson name for display"""
        # Remove common patterns
        name = re.sub(r'^\d+[\.\-_\s]*', '', name)  # Remove leading numbers
        name = re.sub(r'[-_]+', ' ', name)  # Replace dashes/underscores with spaces
        name = ' '.join(word.capitalize() for word in name.split() if word)
        return name if name.strip() else "Untitled Lesson"

    @staticmethod
    def _calculate_completion_stats(node: DirectoryNode) -> Dict[str, Any]:
        """Calculate completion statistics for a directory node"""
        total_lessons = 0
        completed_lessons = 0
        
        def count_lessons_recursive(n: DirectoryNode):
            nonlocal total_lessons, completed_lessons
            
            # Count lessons in this node
            for lesson in n.lessons:
                total_lessons += 1
                if lesson.completed:
                    completed_lessons += 1
            
            # Recursively count in children
            for child in n.children.values():
                count_lessons_recursive(child)
        
        count_lessons_recursive(node)
        
        completion_percentage = (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
        
        return {
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'completion_percentage': round(completion_percentage, 1)
        }


class ProgressTracker:
    """Handles progress tracking and persistence"""

    @staticmethod
    def load_progress(course: Course) -> Dict[str, Any]:
        """Load progress from JSON file"""
        try:
            with open(course.progress_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def save_progress(course: Course, progress_data: Dict[str, Any]):
        """Save progress to JSON file"""
        try:
            with open(course.progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
        except Exception as e:
            print(f"Error saving progress: {e}")

    @staticmethod
    def update_lesson_progress(course: Course, lesson_path: str, completed: bool = False, progress_seconds: int = 0):
        """Update progress for specific lesson by path"""
        progress = ProgressTracker.load_progress(course)
        
        progress[lesson_path] = {
            'completed': completed,
            'progress_seconds': progress_seconds,
            'last_accessed': datetime.now().isoformat()
        }
        
        # Update last accessed path
        progress['last_accessed_path'] = lesson_path
        
        ProgressTracker.save_progress(course, progress)

    @staticmethod
    def apply_progress_to_tree(course: Course):
        """Apply saved progress to the course tree"""
        progress = ProgressTracker.load_progress(course)
        
        def apply_to_node(node: DirectoryNode):
            # Apply progress to lessons in this node
            for lesson in node.lessons:
                lesson_path = os.path.relpath(lesson.path, course.path)
                lesson_path = lesson_path.replace('\\', '/')
                if lesson_path.startswith('/'):
                    lesson_path = lesson_path[1:]
                
                # Check both the base path and path with title
                lesson_path_with_title = f"{lesson_path}/{lesson.title.replace(' ', '_')}"
                
                if lesson_path in progress:
                    lesson.completed = progress[lesson_path].get('completed', False)
                    lesson.last_accessed = progress[lesson_path].get('last_accessed')
                    lesson.progress_seconds = progress[lesson_path].get('progress_seconds', 0)
                elif lesson_path_with_title in progress:
                    lesson.completed = progress[lesson_path_with_title].get('completed', False)
                    lesson.last_accessed = progress[lesson_path_with_title].get('last_accessed')
                    lesson.progress_seconds = progress[lesson_path_with_title].get('progress_seconds', 0)
            
            # Recursively apply to children
            for child in node.children.values():
                apply_to_node(child)
        
        apply_to_node(course.root_node)
        course.last_accessed_path = progress.get('last_accessed_path')

    @staticmethod
    def get_completion_stats(course: Course) -> Dict[str, Any]:
        """Calculate completion statistics"""
        return DynamicCourseParser._calculate_completion_stats(course.root_node)


# Global course storage
current_course = None


@app.route('/')
def index():
    """Main dashboard"""
    global current_course

    if current_course is None:
        # Show dashboard with course selection option
        return render_template('course_dashboard.html',
                               course=None,
                               stats={'total_lessons': 0, 'completed_lessons': 0, 'completion_percentage': 0})

    # Apply progress data to tree
    ProgressTracker.apply_progress_to_tree(current_course)
    stats = ProgressTracker.get_completion_stats(current_course)

    return render_template('course_dashboard.html',
                           course=current_course,
                           stats=stats)


@app.route('/browse')
def browse_directories():
    """Browse directories for course selection"""
    path = request.args.get('path', '')
    
    try:
        # If no path specified, start with available drives on Windows
        if not path:
            import platform
            if platform.system() == 'Windows':
                # Get available drives on Windows
                import string
                drives = []
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if os.path.exists(drive):
                        drives.append({
                            'name': f"Drive {letter}:",
                            'path': drive,
                            'media_files': 0,
                            'is_course_candidate': False
                        })
                print(f"Returning {len(drives)} drives")
                return jsonify({
                    'current_path': 'Select a Drive',
                    'parent_path': None,
                    'directories': drives
                })
            else:
                # On other systems, start from home directory
                path = str(Path.home())

        current_path = Path(path)
        if not current_path.exists() or not current_path.is_dir():
            # Fallback to home directory if path doesn't exist
            current_path = Path.home()

        print(f"Browsing directory: {current_path}")

        # Get directories and basic info
        directories = []
        try:
            for item in sorted(current_path.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    try:
                        # Check if this looks like a course directory
                        media_count = len([f for f in item.rglob('*')
                                           if f.suffix.lower() in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS])

                        directories.append({
                            'name': item.name,
                            'path': str(item),
                            'media_files': media_count,
                            'is_course_candidate': media_count > 0
                        })
                    except (PermissionError, OSError):
                        directories.append({
                            'name': item.name + " (Access Denied)",
                            'path': str(item),
                            'media_files': 0,
                            'is_course_candidate': False
                        })
        except (PermissionError, OSError) as e:
            print(f"Access denied to {current_path}: {str(e)}")
            return jsonify({'error': f'Access denied to {current_path}: {str(e)}'}), 403

        # Determine parent path
        parent = None
        if current_path.parent != current_path:
            try:
                parent = str(current_path.parent)
            except (PermissionError, OSError):
                pass

        print(f"Found {len(directories)} directories")
        return jsonify({
            'current_path': str(current_path),
            'parent_path': parent,
            'directories': directories
        })

    except Exception as e:
        print(f"Error in browse_directories: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/load_course', methods=['POST'])
def load_course():
    """Load course from selected directory"""
    global current_course

    data = request.json
    course_path = data.get('course_path')

    if not course_path or not os.path.exists(course_path):
        return jsonify({'error': 'Invalid course path'}), 400

    try:
        current_course = DynamicCourseParser.scan_directory(course_path)
        return jsonify({'success': True, 'course_name': current_course.name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/lesson/<path:lesson_path>')
def view_lesson(lesson_path: str):
    """View specific lesson by path"""
    global current_course

    if not current_course:
        return redirect(url_for('index'))

    # Find the lesson in the tree
    lesson = find_lesson_in_tree(current_course.root_node, lesson_path)
    
    if not lesson:
        return redirect(url_for('index'))

    # Get all lessons for navigation
    all_lessons = get_all_lessons(current_course.root_node)
    current_index = -1
    
    # Find current lesson index
    for i, (path, lesson_obj) in enumerate(all_lessons):
        if lesson_obj == lesson:
            current_index = i
            break
    
    # Get next and previous lessons
    prev_lesson = None
    next_lesson = None
    
    if current_index > 0:
        prev_lesson = all_lessons[current_index - 1][0]
    
    if current_index < len(all_lessons) - 1:
        next_lesson = all_lessons[current_index + 1][0]

    # Update last accessed
    ProgressTracker.update_lesson_progress(current_course, lesson_path)

    return render_template('lesson_view.html',
                           course=current_course,
                           lesson=lesson,
                           lesson_path=lesson_path,
                           prev_lesson=prev_lesson,
                           next_lesson=next_lesson)


def get_lesson_url(lesson: Lesson, course_path: str) -> str:
    """Generate the URL for a lesson"""
    # Create relative path from course root
    lesson_file_path = os.path.relpath(lesson.path, course_path)
    lesson_file_path = lesson_file_path.replace('\\', '/')
    if lesson_file_path.startswith('/'):
        lesson_file_path = lesson_file_path[1:]
    
    # Append lesson title for uniqueness
    lesson_url = f"{lesson_file_path}/{lesson.title.replace(' ', '_')}"
    return lesson_url


def find_lesson_in_tree(node: DirectoryNode, target_path: str) -> Optional[Lesson]:
    """Find a lesson in the tree by path"""
    # Check lessons in current node
    for lesson in node.lessons:
        lesson_url = get_lesson_url(lesson, current_course.path)
        
        # Check multiple possible path formats
        lesson_file_path = os.path.relpath(lesson.path, current_course.path)
        lesson_file_path = lesson_file_path.replace('\\', '/')
        if lesson_file_path.startswith('/'):
            lesson_file_path = lesson_file_path[1:]
        
        # Also check with lesson title appended
        lesson_path_with_title = f"{lesson_file_path}/{lesson.title.replace(' ', '_')}"
        
        if (lesson_url == target_path or 
            lesson_file_path == target_path or 
            lesson_path_with_title == target_path):
            return lesson
    
    # Recursively search children
    for child in node.children.values():
        result = find_lesson_in_tree(child, target_path)
        if result:
            return result
    
    return None


def get_all_lessons(node: DirectoryNode) -> List[Tuple[str, Lesson]]:
    """Get all lessons from the tree with their paths"""
    lessons = []
    
    def collect_lessons(n: DirectoryNode, current_path: str = ""):
        # Add lessons from this node
        for lesson in n.lessons:
            lesson_url = get_lesson_url(lesson, current_course.path)
            lessons.append((lesson_url, lesson))
        
        # Recursively collect from children
        for child in n.children.values():
            collect_lessons(child, current_path)
    
    collect_lessons(node)
    return lessons


@app.route('/api/progress', methods=['POST'])
def update_progress():
    """API endpoint to update lesson progress"""
    global current_course

    if not current_course:
        return jsonify({'error': 'No course loaded'}), 400

    data = request.json
    lesson_path = data.get('lesson_path')
    completed = data.get('completed', False)
    progress_seconds = data.get('progress_seconds', 0)

    try:
        ProgressTracker.update_lesson_progress(
            current_course, lesson_path, completed, progress_seconds
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/files/<path:filepath>')
def serve_file(filepath):
    """Serve course files"""
    global current_course

    if not current_course:
        return "No course loaded", 404

    # Security: ensure file is within course directory
    try:
        # URL decode the filepath and normalize it
        from urllib.parse import unquote
        decoded_filepath = unquote(filepath)
        
        # Construct the full path relative to the course directory
        full_path = os.path.join(current_course.path, decoded_filepath)
        full_path = os.path.abspath(full_path)
        course_path = os.path.abspath(current_course.path)

        print(f"File request: {filepath}")
        print(f"Decoded filepath: {decoded_filepath}")
        print(f"Full path: {full_path}")
        print(f"Course path: {course_path}")

        # Security check: ensure file is within course directory
        if not full_path.startswith(course_path):
            print(f"Access denied: {full_path} not in {course_path}")
            return "Access denied", 403

        if not os.path.exists(full_path):
            print(f"File not found: {full_path}")
            return "File not found", 404

        print(f"Serving file: {full_path}")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        return send_file(full_path, mimetype=mime_type)
    except Exception as e:
        print(f"Error serving file: {str(e)}")
        return f"Error serving file: {str(e)}", 500

@app.route('/health')
def healthcheck():
    """Healthcheck endpoint for Docker"""
    return jsonify({"status": "healthy"}), 200

@app.route('/reset_course')
def reset_course():
    """Reset current course selection"""
    global current_course
    current_course = None
    return redirect(url_for('index'))


def create_templates():
    """Create basic template files if they don't exist"""
    templates_dir = Path('templates')
    templates_dir.mkdir(exist_ok=True)

    # Basic select course template
    select_template = '''<!DOCTYPE html>
<html>
<head>
    <title>OfflineU - Select Course</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 800px; margin: 0 auto; }
        .directory { padding: 10px; border: 1px solid #ddd; margin: 5px 0; cursor: pointer; }
        .directory:hover { background-color: #f0f0f0; }
        .course-candidate { background-color: #e8f5e8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>OfflineU - Course Selection</h1>
        <div id="browser"></div>
        <script>
            // Basic directory browser implementation
            function loadDirectories(path = '') {
                fetch(`/browse?path=${encodeURIComponent(path)}`)
                    .then(r => r.json())
                    .then(data => {
                        const browser = document.getElementById('browser');
                        browser.innerHTML = `
                            <h3>Current: ${data.current_path}</h3>
                            ${data.parent_path ? `<div class="directory" onclick="loadDirectories('${data.parent_path}')">📁 .. (Parent)</div>` : ''}
                            ${data.directories.map(dir => `
                                <div class="directory ${dir.is_course_candidate ? 'course-candidate' : ''}" 
                                     onclick="${dir.is_course_candidate ? `loadCourse('${dir.path}')` : `loadDirectories('${dir.path}')`}">
                                    📁 ${dir.name} ${dir.media_files > 0 ? `(${dir.media_files} media files)` : ''}
                                </div>
                            `).join('')}
                        `;
                    });
            }

            function loadCourse(path) {
                fetch('/load_course', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({course_path: path})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    } else {
                        alert('Error: ' + data.error);
                    }
                });
            }

            loadDirectories();
        </script>
    </div>
</body>
</html>'''

    # Basic course dashboard template
    dashboard_template = '''<!DOCTYPE html>
<html>
<head>
    <title>OfflineU - {{ course.name }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .module { margin: 20px 0; border: 1px solid #ddd; padding: 15px; }
        .lesson { padding: 8px; margin: 5px 0; border-left: 4px solid #ddd; }
        .lesson.completed { border-left-color: #4CAF50; background-color: #f8fff8; }
        .lesson a { text-decoration: none; color: #333; }
        .lesson:hover { background-color: #f0f0f0; }
        .progress { background-color: #f0f0f0; height: 20px; border-radius: 10px; overflow: hidden; }
        .progress-bar { background-color: #4CAF50; height: 100%; transition: width 0.3s; }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ course.name }}</h1>
        <div class="progress">
            <div class="progress-bar" style="width: {{ stats.completion_percentage }}%"></div>
        </div>
        <p>Progress: {{ stats.completed_lessons }}/{{ stats.total_lessons }} lessons ({{ stats.completion_percentage }}%)</p>

        {% for module_idx, module in course.modules|enumerate %}
        <div class="module">
            <h2>{{ module.title }}</h2>
            {% for lesson_idx, lesson in module.lessons|enumerate %}
            <div class="lesson {% if lesson.completed %}completed{% endif %}">
                <a href="/lesson/{{ module_idx }}/{{ lesson_idx }}">
                    {{ lesson.title }} 
                    <small>({{ lesson.lesson_type }})</small>
                    {% if lesson.completed %}✓{% endif %}
                </a>
            </div>
            {% endfor %}
        </div>
        {% endfor %}

        <p><a href="/reset_course">Select Different Course</a></p>
    </div>
</body>
</html>'''

    # Basic lesson view template
    lesson_template = '''<!DOCTYPE html>
<html>
<head>
    <title>{{ lesson.title }} - {{ course.name }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        video, audio { width: 100%; max-width: 800px; }
        .content { margin: 20px 0; }
        .navigation { margin: 20px 0; }
        button { padding: 10px 20px; margin: 5px; cursor: pointer; }
        .file-link { display: block; margin: 5px 0; padding: 5px; background: #f0f0f0; text-decoration: none; color: #333; }
        .file-link:hover { background: #e0e0e0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ lesson.title }}</h1>
        <div class="navigation">
            <a href="/">← Back to Course</a>
            <button onclick="markCompleted()">Mark as Completed</button>
        </div>

        <div class="content">
            {% if lesson.video_file %}
            <h3>Video</h3>
            <video controls preload="metadata" id="video-player">
                <source src="/files/{{ lesson.video_file }}" type="video/mp4">
                {% if lesson.subtitle_file %}
                <track kind="subtitles" src="/files/{{ lesson.subtitle_file }}" srclang="en" label="English">
                {% endif %}
                Your browser does not support the video tag.
            </video>
            {% endif %}

            {% if lesson.audio_file %}
            <h3>Audio</h3>
            <audio controls preload="metadata" id="audio-player">
                <source src="/files/{{ lesson.audio_file }}" type="audio/mp3">
                Your browser does not support the audio tag.
            </audio>
            {% endif %}

            {% if lesson.text_files %}
            <h3>Additional Resources</h3>
            {% for text_file in lesson.text_files %}
            <a href="/files/{{ text_file }}" class="file-link" target="_blank">
                📄 {{ text_file.split('/')[-1] }}
            </a>
            {% endfor %}
            {% endif %}
        </div>

        <script>
            function markCompleted() {
                fetch('/api/progress', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        lesson_path: '{{ lesson_path }}',
                        completed: true,
                        progress_seconds: getProgressSeconds()
                    })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        alert('Lesson marked as completed!');
                        window.location.href = '/';
                    }
                });
            }

            function getProgressSeconds() {
                const video = document.getElementById('video-player');
                const audio = document.getElementById('audio-player');
                if (video && !video.paused) return Math.floor(video.currentTime);
                if (audio && !audio.paused) return Math.floor(audio.currentTime);
                return 0;
            }

            // Auto-save progress periodically
            setInterval(() => {
                const seconds = getProgressSeconds();
                if (seconds > 0) {
                    fetch('/api/progress', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            lesson_path: '{{ lesson_path }}',
                            completed: false,
                            progress_seconds: seconds
                        })
                    });
                }
            }, 30000); // Save every 30 seconds
        </script>
    </div>
</body>
</html>'''

    # Write templates to files
    template_files = {
        'select_course.html': select_template,
        'course_dashboard.html': dashboard_template,
        'lesson_view.html': lesson_template
    }

    for filename, content in template_files.items():
        template_path = templates_dir / filename
        if not template_path.exists():
            with open(template_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Created template: {template_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OfflineU Course Viewer & Tracker')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--create-templates', action='store_true', help='Create basic templates')
    parser.add_argument('course_path', nargs='?', help='Path to course directory')

    args = parser.parse_args()

    # Create templates if requested
    if args.create_templates:
        create_templates()
        print("Templates created successfully!")
        if not args.course_path:
            sys.exit(0)

    # Auto-load course if provided
    if args.course_path or os.environ.get('AUTO_LOAD_COURSE'):
        course_path = args.course_path or os.environ.get('AUTO_LOAD_COURSE')

        if not os.path.exists(course_path):
            print(f"Error: Course path does not exist: {course_path}", file=sys.stderr)
            sys.exit(1)

        try:
            current_course = DynamicCourseParser.scan_directory(course_path)
            print(f"Auto-loaded course: {current_course.name}")
            print(f"Built dynamic directory tree with {len(current_course.root_node.children)} top-level items")
        except Exception as e:
            print(f"Error loading course: {e}", file=sys.stderr)
            if args.debug:
                import traceback

                traceback.print_exc()
            sys.exit(1)

    # Create templates directory if it doesn't exist
    if not Path('templates').exists():
        print("Templates directory not found. Creating basic templates...")
        create_templates()

    print(f"Starting OfflineU on http://{args.host}:{args.port}")
    print("Use --create-templates to regenerate template files")

    try:
        app.run(debug=args.debug, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\nShutting down OfflineU...")
    except Exception as e:
        print(f"Error starting server: {e}")
        if args.debug:
            import traceback

            traceback.print_exc()
        sys.exit(1)
